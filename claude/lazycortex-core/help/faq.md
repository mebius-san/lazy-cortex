---
chapter_type: faq
summary: Non-obvious answers on install/setup, audit/doctor/optimize, expert runtime (incl. manual ticks and new daemon authoring), memory, routines, git staging, MCP permissions, and change-history search.
last_regen: 2026-08-21
no_diagram: true
source_skills:
  - lazy-core.install
  - lazy-core.setup
  - lazy-core.audit
  - lazy-core.doctor
  - lazy-core.optimize
  - lazy-repo.mark-public
  - lazy-guard.check-public
  - lazy-guard.allow-mcp
  - lazy-routine.register
  - lazy-runtime.recover
  - lazy-runtime.tick
  - lazy-core.daemon-authoring
  - lazy-expert.dispatch-job
  - lazy-expert.collect-job
  - lazy-memory.mark-persona
  - lazy-memory.reflect
  - lazy-core.agent-models
  - lazy-core.git-status
  - lazy-log.recall
  - lazy-log.summary
  - lazy-log.timeline
source_sha: ddfefb0f7c7cd9509a78bd86f8dc930e5e906a56
---
# FAQ

## When should I run `/lazy-core.install` versus `/lazy-core.setup`?

`/lazy-core.install` installs one plugin — `lazycortex-core` — by syncing its rule templates and authoring templates into the target `.claude/` directory, and seeding `lazy.settings.json` with the built-in agent-model defaults. `/lazy-core.setup` is the meta-installer: it discovers every enabled plugin that ships a `<namespace>.install` skill (or opts in via `lazy_setup_phase:` frontmatter) and runs them all in the correct order, with `lazy-core.install` going first.

Before any plugin installer runs, `/lazy-core.setup` automatically migrates `.claude/lazy.settings.json` to the current per-section schema (Step 0). This happens transparently — you do not need to run a migration command by hand, and you do not need to know which schema version you are on. If the migration step fails, setup surfaces the reason and stops before touching any plugin files.

Use `/lazy-core.install` directly when you want to re-sync just the core plugin after a `lazycortex-core` update. Use `/lazy-core.setup` after any plugin update, after enabling a new plugin, or on a fresh project clone — it is the single command that brings all plugins current in one pass, settings migration included.

---

## Do I need to migrate `lazy.settings.json` by hand after a plugin update?

No. `/lazy-core.setup` runs a settings migration as its first step (Step 0) before any plugin installer touches the file. The migration ladder upgrades each section of `.claude/lazy.settings.json` to the current schema automatically. The step is transparent: if nothing needs to change, it prints `migrated: 0 sections (N up-to-date)` and continues; if sections are upgraded, it lists each one in the Step 6 report. Only if the migration itself errors (a malformed ladder entry) does setup stop and ask you to investigate.

---

## Do I need to re-run `/lazy-core.install` after a plugin update?

Yes. `/plugin update` refreshes the plugin cache but does not re-sync rule files into `.claude/rules/`. Your project keeps running the old rule content until you explicitly re-run `/lazy-core.install` (or `/lazy-core.setup`, which includes it). The re-run itself is silent: rule files are plugin-owned mirrors, so the install skill byte-compares each one and overwrites whatever has fallen behind, without asking. If you want different content in a rule, write your own rule file rather than editing the mirror — an edited mirror is indistinguishable from a stale one and gets replaced. A rule the plugin no longer ships is left in place, never deleted.

---

## My runtime daemon still behaves like an old version after I updated the plugin — why?

This should now be rare: the daemon checks on every tick whether a newer `lazycortex-core` version is sitting in the plugin cache and, when a supervised deployment finds one, restarts itself in place onto it automatically — no operator action needed. If you still see stale behavior, the remaining cause is the launch shim itself: a small script at `.claude/bin/lazy.runtime.sh` resolves the cached build each time the daemon starts, and if the shim's own content is stale — drifted from the version the plugin currently ships — it can carry an outdated resolution rule. `/lazy-core.install` re-syncs the shim on content drift (state **refreshed** in its report), so re-running it after a plugin update is what gets a supervised daemon's launcher current; `/plugin update` alone only refreshes the cache the shim and the daemon both read from.

---

## Which bump level requires what action from me?

A **patch bump** (e.g. `1.0.0` → `1.0.1`) is safe to drop in with no action — the plugin cache updates automatically when `autoUpdate: true` and the change is backward-compatible. A **minor bump** (e.g. `1.0.0` → `1.1.0`) means new rules, settings keys, or templates were added; re-run `/lazy-core.install` (or `/lazy-core.setup`) to pick them up. A **major bump** (e.g. `1.0.0` → `2.0.0`) means user-data migration is required — read `CHANGELOG.public.md` for the migration steps before re-installing. The README banner at the top of each plugin describes this same contract.

---

## What's the difference between `/lazy-core.audit`, `/lazy-core.doctor`, and `/lazy-core.optimize`?

`/lazy-core.audit` is a read-only startup-context and compliance scan: it shows what actually loads into context (rule sizes, loading behavior), checks skill/agent/rule authoring compliance (Execution-Discipline preamble, no-Optional headings, narrative padding, and — for skills, agents, and commands alike — whether each `description:` states an invocation trigger rather than just a mechanism), checks help-doc coverage and staleness against each plugin's README scenarios, and reports the expert-runtime config across fourteen sub-checks. It makes no changes.

`/lazy-core.doctor` is the broader health check: it verifies consistency across rules, agents, skills, commands, settings, memory, hooks, and CLAUDE.md files, confirms every installed plugin is at the latest marketplace version, and delegates to sibling audit skills — `lazy-guard.check-public`, plus each installed plugin's own audit skill when it ships one, including `lazycortex-obsidian` and `lazycortex-python` — when they apply. Unlike audit, it offers targeted fixes you can accept interactively, plus a per-warning waive loop.

`/lazy-core.optimize` is action-oriented: it slims oversized rule files (moving reference material into agent definitions) and audits global `settings.json` for project-specific entries that should move to local settings. Run it when startup feels slow or after adding new rules/agents — audit and doctor tell you something is off, optimize is one of the skills that fixes it.

Run `/lazy-core.audit` for a quick read on context footprint, `/lazy-core.doctor` when something in the config feels broken and you want fixes offered, and `/lazy-core.optimize` specifically to shrink startup context.

---

## What is `lazy.settings.json` and why does it exist alongside `settings.json`?

`lazy.settings.json` is a separate config file used by the `lazy-core.model-router` hook to route subagent dispatches to model tiers (`haiku`, `sonnet`, `opus`, or `default`). It lives alongside the Claude Code `settings.json` files but is not read by Claude Code itself — it is read by the hook at dispatch time.

The file exists separately because model-routing preferences are architectural decisions (cheapest agent for Explore work, strongest for commit-message generation) that belong in a structured config, not interleaved with per-tool permission lists. Run `/lazy-core.agent-models` to fill and update it interactively. The scope rules are: entries under `_user.*` go to the global `~/.claude/lazy.settings.json`; entries under `_project.*` go to the project `.claude/lazy.settings.json`; plugin-domain groups go to the plugin's own install scope.

---

## What is safe to commit to git, and what should stay gitignored?

The tracked `settings.json` files (global `~/.claude/settings.json` and project `.claude/settings.json`) are for enablement-only entries: `enabledPlugins`, `enabledMcpjsonServers`, `hooks` registrations, non-secret `env` vars, model selection, and status-line config. Per-tool permission entries (`permissions.allow`, `permissions.ask`), `additionalDirectories`, and machine-specific `env` values belong in the gitignored `settings.local.json` files. Committing permission lists leaks your personal risk preferences to teammates who may have different policies. The `lazy-guard.settings` PreToolUse hook enforces this split by intercepting writes to settings files that violate it.

The same split applies to `lazy.settings.json[daemon].metrics`: the `enabled` flag and `repo_label` are tracked (they're a shared design decision), while the allocated port lives only in the gitignored local overlay, because a port that is free on one machine can be taken on another. `daemon.run_here` is the deliberate exception to "per-machine stays local" — it is a hostname-to-checkout-path map and lives in the **tracked** file on purpose, so the pairing travels to every clone (see the Dropbox/iCloud question below).

---

## When should I use `/lazy-core.agent-models` versus editing `lazy.settings.json` by hand?

Always use `/lazy-core.agent-models`. The skill enforces structural routing rules that hand-edits routinely miss: `_user.*` group entries belong in the global `~/.claude/lazy.settings.json`, `_project.*` entries belong in the project `.claude/lazy.settings.json`, and plugin-domain groups follow the plugin's install scope. Writing an entry to the wrong file produces a split-brain config that `lazy-core.audit` will flag as a finding. The skill also reads `default-tiers.json` to surface curated tier suggestions for every known LazyCortex agent, and it is idempotent — a second run on a fully-configured vault returns "nothing to do" immediately. If you want to see what it would write without touching anything, pass `--dry-run`.

The only time hand-editing `lazy.settings.json` is appropriate is when you are deliberately overriding a tier for a single project (using `/lazy-core.agent-models --scope=project`) and you want to inspect or revert the exact entry afterward. Even then, use the skill for the write and only read the file to verify.

When `/lazy-core.agent-models` runs as part of a non-interactive rollout chain (no wizard, no user channel), only the curated batch behaves the same as an interactive run: entries whose dispatch string is a key in `default-tiers.json` still auto-apply at their template tier, because a plugin-shipped default is a recorded decision, not a guess. Everything else — agents with no curated default — is left missing and reported `needs-interactive`; a normal interactive run of the skill picks those up afterward.

The skill also prunes automatically: any configured entry whose plugin agent file has since been deleted (the plugin is still installed, but its cache no longer has that agent stem) is removed with no prompt, in both interactive and non-interactive runs — a tier for a deleted agent is dead config, not a decision. If a pruned dispatch string is still referenced by an expert's `agent` field, the skill leaves that expert entry alone and reports a warning instead of guessing; you decide whether to repoint or remove it.

---

## When does `/lazy-core.setup` help versus running each plugin's install skill manually?

`/lazy-core.setup` is the right default after any multi-plugin change: it discovers all enabled plugins automatically (no list to maintain), migrates `lazy.settings.json` to the current schema before any installer runs, resolves dependency order (core before others, post-install configurators last), and continues even if one child fails so you get a single coherent summary rather than hunting for which installer you missed. It is also idempotent — every child skill is idempotent, so re-running setup after a partial failure is safe.

Run a plugin's install skill directly only when you want to re-sync exactly one plugin and you are certain it has no cross-plugin dependencies. The most common case is a `lazycortex-core`-only update where running `/lazy-core.install` is faster and clearer. For everything else — fresh clone, adding a new plugin, upgrading multiple plugins at once — `/lazy-core.setup` is the single command that brings the whole project current.

---

## How does `/lazy-guard.allow-mcp` decide which MCP tools to auto-allow?

It uses a 3-bucket classifier applied per tool, not per server. Read-shaped verbs (`get_*`, `list_*`, `search*`, `status*`, and similar) and low-risk writes that create easily-undone content go to `permissions.allow` — no prompt. Irreversible or hard-to-recover verbs (`delete_*`, `remove_*`, `reset`, `checkout`, force-pushes) go to `permissions.ask` — always prompt. Everything else — medium-risk tools like `git_commit` — is skipped entirely: neither list, so Claude Code's built-in per-call prompt still applies and you decide in the moment. A tool you've already pinned to a bucket yourself is never re-classified or moved by a later run.

When `/lazy-guard.allow-mcp` runs inside a non-interactive rollout chain, it never guesses at a preference. Additions at a scope that's already inferable from existing entries apply silently — that's a mechanical extension of a trust decision you already made interactively. Anything that would reverse a prior `allow` choice, resolve an ambiguous or undetermined scope, or decide whether to install the SessionStart preload hook at all is left untouched and reported `needs-interactive`, waiting for you to run the skill yourself.

By default the skill writes to the gitignored `settings.local.json` at the appropriate scope (global for servers defined in `~/.mcp.json`, project for servers defined in `./.mcp.json`) rather than the tracked `settings.json`, because permission choices are personal and shouldn't leak into commits teammates inherit. It always shows the planned diff — allow adds, ask adds, skipped tools — before writing.

---

## Do I need to enable the expert runtime, or is it on by default?

The expert runtime is opt-in per repo. When you run `/lazy-core.install`, a wizard phase asks whether to bootstrap runtime and experts for the current repo. If you answer yes, the skill writes the flat `daemon` and `routines` sections into `.claude/lazy.settings.json`, creates `lazy.settings.json[experts]`, copies the `lazy.runtime.sh` shim to `.claude/bin/`, and adds `.experts/` to `.gitignore`. It also offers to install a daemon supervisor (macOS launchd or Linux systemd) and registers the `lazy-expert.pump` routine automatically once you add at least one expert. If you skip that phase or answer no, none of those files are created and the `/lazy-expert.*` skills will abort at Step 2 with "`.experts/` not initialised — run `/lazy-core.install` first."

To enable it later without re-running the full install flow, run `/lazy-core.install` again — it is idempotent and will offer the runtime wizard phase again.

---

## Does `/lazy-core.install` set up monitoring for the runtime daemon?

Yes, but only on a checkout that actually runs the daemon locally. Once the earlier install wizard confirms this machine and checkout are the pair on record (`run_here`), a later step asks once whether to enable the daemon's Prometheus `/metrics` endpoint — exposing routine ticks, errors, tokens, and queue depth on a loopback HTTP port for a Prometheus-compatible scraper. Answering "No" is recorded permanently and you are never asked again on that checkout; re-running `/lazy-core.install` reuses the recorded answer instead of re-asking.

Answering "Yes" allocates a free port sequentially starting from `9464` — reusing this checkout's already-recorded port on re-runs instead of picking a new one — and splits where the decision is written: the `enabled` flag and a human-readable `repo_label` (default `local-<folder name>`) go into the tracked `lazy.settings.json[daemon].metrics`, shared across machines, while the allocated port goes into the gitignored per-machine overlay, because a port that's free on one machine may be taken on another. The step then regenerates a host-wide Prometheus scrape-targets file so an external Prometheus with a `file_sd_configs` pointer picks up every locally running daemon with zero manual edits.

If the daemon later starts and finds its recorded port already taken by something else, it does not crash-loop — it records the conflict as an incident and keeps running without metrics until the conflict is resolved.

---

## My checkout is on Dropbox/iCloud/Syncthing and shows up on more than one machine — won't `run_here` start a daemon on all of them?

It would, if `run_here` only accepted `true`/`false` — but that shape is retired. `daemon.run_here` is now a hostname-to-checkout-path map, for example `{"nexus": "~/lazy-runtime/Money"}`, stored in the **tracked** `lazy.settings.json` so the pairing travels with the project to every clone (a gitignored overlay would never reach a machine that cloned the repo independently — exactly where a second daemon would appear). Neither half of the pair decides alone: the hostname says which machine, the path says which of that machine's checkouts drives the daemon — a single machine commonly holds more than one checkout of the same project (a working copy plus the one the daemon runs from), and naming only the host would collide between them the same way a bare `true` used to collide across synced machines.

`/lazy-core.install` compares the map against the machine's own hostname (lowercased) and the checkout's own resolved path (symlinks included, so a symlinked path still matches). The named pair installs the supervisor as normal. Every other machine — and every other checkout on the named machine — both skips the supervisor install AND tears down any supervisor unit it already has for that checkout, so re-running `/lazy-core.install` anywhere that shouldn't be running the daemon self-heals a leaked one instead of leaving it running. The daemon itself also refuses to start on a checkout the map doesn't name, even while `daemon.enabled` stays `true`, so a leaked supervisor can't outlive the map even if you never get around to re-running install there. An empty map (`{}`) names nothing at all — the project stays daemon-enabled but nothing drives it until you point the map at a checkout.

Edit the map by hand — add or remove a `"<hostname>": "<path>"` entry — then re-run `/lazy-core.install` to apply it; entries recorded for other machines are left untouched. If the file still carries the retired shape (a bare boolean, or a plain list of hostnames from an install that predates the map), `/lazy-core.install` reports `run-here-invalid`, prints the offending value, and re-asks the Gate 2 question so your answer replaces it outright — the daemon refuses to start until the map is in the current shape.

---

## What payload fields does `/lazy-expert.dispatch-job` require?

Every job payload must contain three fields: `kind` (the job type, e.g. `"doc-review"`), `role` (the expert role to handle it, e.g. `"designer"`), and `request` (the task description string). These are the minimum the protocol contract enforces; if any field is missing, dispatch aborts with "payload missing required field(s): `<list>`."

Optional fields — `source` (array of input file paths), `context` (array of context file paths), and `result` (array of expected output paths) — are supported but not required. Protocol-specific extras are also allowed. The full contract is in `claude/lazycortex-core/references/lazy-core.expert-protocols-contract.md`.

---

## What happens if I dispatch a job for an expert that is not registered?

`/lazy-expert.dispatch-job` loads `lazy.settings.json[experts]` and looks up the expert name you provided. If the key is absent, the skill aborts with "`<expert_name>` is not registered in `lazy.settings.json[experts]`" — no job directory is created. Register the expert first via `/lazy-core.install` (expert wizard) or, if the expert was recently added by enabling a plugin, re-run `/lazy-core.setup` to pick it up, then re-dispatch.

---

## How do I check on a job I dispatched, and get its result?

Run `/lazy-expert.list-jobs` to see every job in the queue, optionally filtered by `expert` or `status` (`queued`, `active`, `cancelled`, `dead`, `done`, `failed`), sorted oldest-first with an age in seconds. Once a job's status is `done`, run `/lazy-expert.collect-job <expert> <job_id>` — it returns `{status, response}` and, on success, lists the paths of the result files so you can `Read` them directly. If the job is still `pending`, `collect-job` reports that and you try again later; there is no blocking wait built in.

---

## Can my experts use MCP servers?

Yes, but every expert spawn is hermetic by default. When the daemon or `/lazy-expert.dispatch-job` launches an expert, the underlying `claude -p` spawn always runs with `--strict-mcp-config`, which means it never inherits your ambient MCP servers from `~/.claude.json` or the project's `.mcp.json` — even servers you already approved interactively. This is deliberate: a headless spawn has no TTY, so an MCP server that expects interactive auth at startup would hang until the job times out.

If an expert genuinely needs one or more MCP servers, declare them per-expert via the `mcp_config` field on that expert's entry in `lazy.settings.json[experts]` — a path (or list of paths) to an MCP-config JSON file whose `mcpServers` object lists only the servers that expert is allowed to use. Only servers that initialize cleanly without interactive input work in this context; a server that needs a login prompt on first use will still hang the spawn even when it is listed in `mcp_config`. Leave `mcp_config` unset for experts that don't need any servers — that is the hermetic default, and it is the safer choice unless you have a concrete reason to widen it.

---

## Does every lazycortex hook run on every `Bash` call inside an expert spawn?

No — by default, none of them do. Every core hook (`git-guard`, `check-public`, `model-router`, `settings-guard`, `commit-recorder`) checks an allow-list environment variable as its first action, and the pump exports that variable on every expert spawn. When it is present but the expert's name is not on the list, the hook no-ops immediately instead of running its checks — this removes the tens-of-seconds `check-public` / `git-guard` tax on every `Bash` call inside a headless expert, since none of those interactive-commit checks apply to a spawn that never touches the operator's own commit.

An expert that genuinely needs a specific hook opts it back in on its entry in `lazy.settings.json[experts]`:

```
experts:
  <name>:
    hooks:
      enabled: [git-guard]
```

Only the named hooks run for that expert's spawns; every other lazycortex hook stays gated off.

---

## When does the runtime daemon halt, and how do I recover it?

The daemon halts in two distinct situations. A **working-tree halt** (`uncommitted_changes`) happens when a routine or expert job leaves the repo in a dirty state — the daemon stops rather than proceeding with uncommitted changes in the tree. A **remote-sync halt** (`git_pull_diverged`, `git_push_failed`, `git_remote_unavailable`) happens when the daemon's pre- or post-tick git sync fails unrecoverably.

Run `/lazy-runtime.recover` to unblock it. For working-tree halts the skill walks you through four options: commit the dirty files (you supply the message), stash them, discard them, or abort and leave the halt in place. For remote-sync halts the skill surfaces reason-specific guidance (the exact git commands to inspect and fix the divergence or push failure) and waits for you to confirm you have resolved the situation before clearing the halt block. Once the halt block is cleared from `.runtime/state.json`, the daemon resumes on its next iteration.

If the cleanup does not produce a clean tree, the skill reports "working tree still dirty; refusing to resume" and leaves the halt intact — inspect with `git status` and re-run the skill.

---

## Can I trigger my own automation when the daemon pushes?

Yes. Set `daemon.git.post_push_hook` to a shell command in the `daemon.git` block of `lazy.settings.json`. It fires immediately after the daemon's post-iteration push actually advances `origin/<base_branch>` — whether that push was a plain fast-forward or the result of a post-rebase retry — with `LAZY_PUSH_REPO` (absolute repo path), `LAZY_PUSH_BRANCH`, `LAZY_PUSH_REMOTE`, `LAZY_PUSH_OLD_SHA`, and `LAZY_PUSH_NEW_SHA` set in the hook's environment. That is enough to trigger a deploy, post a notification, or kick off any other automation keyed to what the daemon just pushed.

The hook is fully isolated from the daemon's own tick: a non-zero exit, a timeout past `post_push_timeout_sec` (30 seconds by default), or a spawn failure is journaled and never halts the daemon, retries the push, or fails the tick. It also never fires when nothing was actually pushed — an in-sync tick, the already-published fallthrough, and a discarded rebase-conflict retry all skip it. This only applies when `daemon.git.remote_sync` is `"pull_push"`; a `"pull"`-only daemon never pushes, so the hook never fires.

---

## How do I run routines and drain queued jobs on a checkout without a live daemon?

Run `/lazy-runtime.tick [<routine-name>] [--drain]`. It runs the daemon's own primitives by hand, in the daemon's own serial order, on a checkout whose daemon is not running. With no arguments it runs a single iteration — every due routine in priority order, then at most one READY job through the pump (the daemon's own single-spawn ceiling). `--drain` repeats iterations, sleeping between them exactly as the daemon would, until nothing is due and the queue is empty — it stops early on a halt, a dirty tree, a raised rate-limit flag, or a pass that made no progress. Naming a routine runs only that one, ignoring both its interval and `--drain`.

It refuses outright if the checkout's own supervisor unit already holds a live daemon — a concurrent manual tick would race it over the working tree, the git index, and the job queue; stop the supervisor first (or run the tick on a different checkout) rather than forcing it. Commits land exactly as the daemon's own would (per-routine, bot identities), but the push is deferred: nothing publishes during a manual tick, and the commits wait on the branch for the next pushing iteration the daemon itself runs after you restart it. If a routine halts mid-tick, `/lazy-runtime.recover` explains and clears it, same as it would for the daemon.

---

## I'm writing a new periodic process that calls an LLM — how do I avoid it getting rate-limited off my subscription?

Run `/lazy-core.daemon-authoring` before the first line of the launch command exists. Its first question is whether the work needs a new daemon at all: if the target repo already runs the lazycortex runtime (a `routines` section in `lazy.settings.json`, or a `com.lazycortex.runtime.*` supervisor unit for the checkout), the answer is a **routine** — register it via `/lazy-routine.register` and let the existing daemon drive it, since it already carries the rate-limit guard, serial scheduling, git discipline, and the error ledger. Writing a second daemon next to a running one is the wrong move. Only a genuinely standalone process — no runtime present, or a lifecycle the runtime can't host — gets a new daemon.

For a standalone daemon, every LLM call it makes must go through `~/.local/bin/lazy-claude` by absolute path, never the bare word — launchd and cron hand the process their own minimal `PATH`, which won't resolve a bare `lazy-claude`. Exit code 75 from the wrapper is not an error: it means the host's subscription rate-limit window is closed and the call was refused before burning tokens, so the daemon should treat it as a quiet skip and try again on the next schedule rather than retrying in a loop or alerting. Exit 69 means no real `claude` executable was found on `PATH` and is worth surfacing. Turning the guard off for one daemon means putting the bare word `claude` back in its launch command — the wrapper itself has no configuration to disable.

`/lazy-core.daemon-authoring` also hands over a launchd plist skeleton (a systemd user timer/service pair on Linux) encoding the practices that keep a standalone daemon debuggable: `StartInterval` over `KeepAlive` for periodic work, an explicit `PATH` in the environment so both the wrapper and any tools the daemon shells out to resolve, and fixed stdout/stderr log paths since launchd captures nothing without them. This requires `/lazy-core.install` to have already run at least once on the host — that is what creates `~/.local/bin/lazy-claude` in the first place.

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

## What's the difference between `/lazy-memory.write` and `/lazy-memory.reflect`?

`/lazy-memory.write` is the atomic per-note writer — it's how an expert commits a single new memory note to `.memory/<expert>/` during or after a job. `/lazy-memory.reflect <expert>` is a consolidation pass: it dispatches a `kind=reflect` job that hands the expert its own recent run logs (default: last 30 days) plus its current memory notes, and asks it to distill patterns worth retaining — calling `/lazy-memory.write` itself if it finds anything, or returning `outcome=empty` if there is nothing new to consolidate. Both require the expert to be persona-marked first (`/lazy-memory.mark-persona`); `reflect` refuses non-persona-marked experts outright.

Run `reflect` periodically (or via the daemon's `memory-reflect-all` routine, if you enable it) rather than expecting memory to accumulate automatically — dispatching jobs alone only produces run logs, and reflect is what turns those logs into durable notes.

---

## What is a waivable WARN versus an unwaivable FAIL in the guard scanner?

The distinction is whether the finding represents a certain security boundary violation or a context-dependent judgment call.

**FAILs are never waivable.** They cover secrets that would be directly exploitable if the repo went public: private keys, AWS access keys, API key or token literals, bearer tokens, high-entropy base64 on lines that look like credential assignments, and connection strings with embedded credentials. The scanner blocks the commit or the public-repo workflow and requires you to encrypt, template-ize, or redact the value before proceeding. There is no waiver path for these — the threat model does not have a "it's fine this time" branch.

**WARNs are waivable with a documented reason.** They cover findings that are often real problems but sometimes legitimate: email addresses (yours on a public README is fine; a customer's in a config is not), service user IDs, Tailscale or public IP addresses, internal hostnames, and hardcoded local paths (`/Users/…` or `~/Dropbox/…` style). To accept a WARN, re-run `/lazy-guard.check-public` and pick the "Add waiver" option when the scanner presents the finding — the skill writes the waiver entry including check ID, scope glob, match pattern, reason, and date. Waivers live in `.guard-public.json` and are checked on every subsequent scan.

Author-name findings in tracked manifests (`plugin.json`, `package.json`, etc.) are also WARNs. Set your `public_author` by letting `/lazy-guard.check-public` prompt you for it on first use; it records the value in `.guard-public.json` and auto-waives matching literals on all future scans.

---

## Can I use `lazy-guard.check-public` on a private repo that has a public subtree?

Yes. The skill supports a `public_scopes` array in `.guard-public.json`. When that array is set, only files matching one of its globs are treated as the public surface — everything else is implicitly private and excluded from the scan. The pre-commit hook respects the same array, so commits that only touch files outside the public scopes are not scanned. Run `/lazy-repo.mark-public <glob>` with one or more scope glob arguments to set this up: it adds the globs to `public_scopes`, runs the audit scoped to those paths, walks you through fixes and waivers, and never touches your GitHub repo visibility.

---

## Which `Bash` commands trigger the secret scan and the commit recorder?

Both the `lazy-guard.check-public` pre-commit hook and the `lazy-log.commit-recorder` hook detect a commit by looking for a `git commit` invocation anywhere in the `Bash` command string — not only a command that starts with it. That covers the two shapes people actually type: a chained command like `git add . && git commit -m "..." && git push`, and a flag-prefixed form like `git -C some/dir commit`. `mcp__git__git_commit` calls are always detected, since there is no command string to scan. The secret scan runs on this detection *before* the commit happens, against the staged diff; the commit recorder runs *after*, deciding whether to append an entry to `.logs/commits.jsonl`.

For the recorder specifically, detecting a commit and recording one aren't the same thing — it only appends once a commit has actually landed. In a chained command, a non-zero exit code belongs to whichever segment failed last, so a commit that succeeded followed by a `git push` that failed still reports overall failure. The recorder resolves this by checking whether `HEAD` was committed within the last 60 seconds: if the chain reports failure but `HEAD` is fresh, the commit itself landed and still gets recorded; if the whole chain aborted before `git commit` ever ran, `HEAD` stays stale and nothing is appended. Entries are also deduplicated by SHA, so retrying a failed push after a real commit never double-records it.

---

## Why does `/lazy-core.install` check Python version before anything else?

Every plugin in the lazycortex marketplace requires Python 3.12 or newer. The install skill runs the Python check as Step 0 — before it touches any files — because all plugin hooks (`lazy-guard.check-public.py`, `lazy-guard.settings.py`, `lazy-core.model-router.py`, `lazy-core.git-guard.py`) will fail silently at runtime if the Python floor is not met. Failing at Step 0 with a clear "install Python 3.12 via brew or pyenv" message is better than installing all the rule files and discovering hook failures later.

Note that `/lazy-core.audit` uses a lower floor of Python 3.12 for its own runtime probe — that check covers whether the Python version is sufficient for hooks' `__future__` annotations and f-strings. The 3.12 install-floor is stricter and is set as the single marketplace-wide requirement so all plugins can rely on it without per-plugin version guards.

---

## Which skills support `--dry-run` and what does it do?

Two skills covered in this block accept `--dry-run`:

- `/lazy-core.setup` — builds and previews the install plan (which skills would run, in what order) without executing any of them. The settings migration step (Step 0) still runs in dry-run mode so the preview reflects the post-migration state.
- `/lazy-core.agent-models` — walks the wizard and reports what tier assignments would be written, without touching either `lazy.settings.json` file.

In both cases, `--dry-run` is purely read-only: no files are created or modified, and the skill exits after the preview. It is safe to run at any time and does not require undoing anything afterward.

---

## Why does `git commit` now refuse a bare commit and ask me to name paths?

The git-guard hook's default behavior changed: **pathspec discipline** is now the default mode (`lazy.settings.json["git"]["pathspec_enabled"]` defaults to `true`), and it replaces the staging-window mutex as what most sessions actually hit. Under pathspec discipline the shared git index is treated as the operator's own space — a Claude session never leaves content parked there for a later commit to accidentally sweep up. Concretely: a bare `git commit` (or `-a`/`-am`/`.`/`:/`/a directory pathspec) is refused; every commit must name explicit paths, e.g. `git commit -m "..." -- <path> <path>`. A new file is registered with `git add -N <path>` (no content staged) rather than a plain `git add`; renames and deletes go through Bash `mv`/`rm`, never `git mv`/`git rm` (both auto-stage); `git reset` still works normally if something needs un-parking. The only exceptions are a bare commit mid-merge (git itself refuses a partial commit there) and `--amend` when a pathspec is given or the index is already clean.

If a session's own tooling staged content for you (a skill, a pre-commit pipeline step), fold the paths it reports into your commit pathspec rather than falling back to a bare commit. You don't need to change anything to opt in — the hook enforces the new default and tells you the pathspec form to use whenever it refuses a bare commit.

---

## What is the git staging lock, and when do I need to touch it?

The staging-window mutex is the previous default and is now dormant on a fresh install — it only takes over when you flip `lazy.settings.json["git"]["pathspec_enabled"]` to `false` and `["mutex_enabled"]` to `true`. In that mode, multiple Claude Code sessions sharing one checkout serialize the staging window — from the first `git add` that makes the index non-empty to the `git commit` that empties it again — so only one session stages at a time, with the same auto-break heuristics as before (holder process dead, on a different host, or idle for a while).

`/lazy-core.git-status` and `/lazy-core.git-unlock` only have something to act on under mutex mode; on the pathspec-discipline default no session ever opens a staging window, so there is nothing to inspect or break. Run `/lazy-core.git-status` to check the lock (holder, age, liveness, whether it's currently breakable) without changing anything, and reach for `/lazy-core.git-unlock` — which asks for confirmation before deleting the lock file — only when status shows a lock the automatic heuristics won't break on their own. Setting `lazy.settings.json["git"]["enabled"]` to `false` silences the hook entirely, in either mode.

---

## What's the difference between `lazy-log.recall`, `lazy-log.timeline`, and `lazy-log.summary`?

All three search the same sources — `.logs/changelog.md`, run logs under `.logs/claude/`, raw commits in `.logs/commits.jsonl`, git log, and project memory — but return different shapes. `lazy-log.recall` answers a specific question ("why was X changed?" or "when did we touch Y?") with a ranked table of top matches and the git SHAs you need to `git show`. `lazy-log.timeline` takes a date range or topic — or both — and returns a chronological, day-by-day listing; it's the "what happened when" view, and defaults to the last 7 days if you give no range. `lazy-log.summary` aggregates every match for a topic into a multi-paragraph narrative clustered by sub-theme (design decisions, implementation phases, issues encountered, follow-up work) rather than by date — reach for it when you want "the whole story" of a feature or refactor, not a specific answer or a timeline. All three cite git SHAs so you can `git show <sha>` for the exact change, and all three flag gaps or ambiguity rather than guessing.
