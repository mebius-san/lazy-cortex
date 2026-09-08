---
chapter_type: faq
summary: Non-obvious answers on install, LLM providers, the runtime daemon and experts, routines, scaffolding, git staging, and MCP permissions.
last_regen: 2026-09-08
no_diagram: true
source_skills:
  - lazy-core.install
  - lazy-core.setup
  - lazy-core.audit
  - lazy-core.doctor
  - lazy-core.slim-context
  - lazy-core.agent-models
  - lazy-core.agent-models-seed
  - lazy-core.providers
  - lazy-core.daemon-authoring
  - lazy-core.git-status
  - lazy-core.git-unlock
  - lazy-core.iterate
  - lazy-core.scaffold-local
  - lazy-core.scaffold-sync
  - lazy-repo.mark-public
  - lazy-guard.check-public
  - lazy-guard.allow-mcp
  - lazy-routine.register
  - lazy-routine.unregister
  - lazy-routine.offer-protocols
  - lazy-runtime.recover
  - lazy-runtime.preflight
  - lazy-runtime.tick
  - lazy-expert.dispatch-job
  - lazy-expert.collect-job
  - lazy-expert.cancel-job
  - lazy-expert.list-jobs
  - lazy-memory.write
source_sha: 063baee10c75ba3794390ccf935191d3c564a350
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

## What's the difference between `/lazy-core.audit`, `/lazy-core.doctor`, and `/lazy-core.slim-context`?

`/lazy-core.audit` is a read-only startup-context and compliance scan: it shows what actually loads into context (rule sizes, loading behavior), checks skill/agent/rule authoring compliance (Execution-Discipline preamble, no-Optional headings, narrative padding, and — for skills, agents, and commands alike — whether each `description:` states an invocation trigger rather than just a mechanism), checks help-doc coverage and staleness against each plugin's README scenarios, and reports the expert-runtime config across fourteen sub-checks. It makes no changes.

`/lazy-core.doctor` is the broader health check: it verifies consistency across rules, agents, skills, commands, settings, memory, hooks, and CLAUDE.md files, confirms every installed plugin is at the latest marketplace version, and delegates to sibling audit skills — `lazy-guard.check-public`, plus each installed plugin's own audit skill when it ships one, including `lazycortex-obsidian` and `lazycortex-python` — when they apply. Unlike audit, it offers targeted fixes you can accept interactively, plus a per-warning waive loop.

`/lazy-core.slim-context` is action-oriented: it slims oversized rule files (moving reference material into agent definitions) and audits global `settings.json` for project-specific entries that should move to local settings. Run it when startup feels slow or after adding new rules/agents — audit and doctor tell you something is off, optimize is one of the skills that fixes it.

Run `/lazy-core.audit` for a quick read on context footprint, `/lazy-core.doctor` when something in the config feels broken and you want fixes offered, and `/lazy-core.slim-context` specifically to shrink startup context.

---

## What is `lazy.settings.json` and why does it exist alongside `settings.json`?

`lazy.settings.json` is a separate config file used by the `lazy-core.model-router` hook to route subagent dispatches to model tiers (`haiku`, `sonnet`, `opus`, or `default`). It lives alongside the Claude Code `settings.json` files but is not read by Claude Code itself — it is read by the hook at dispatch time.

The file exists separately because model-routing preferences are architectural decisions (cheapest agent for Explore work, strongest for commit-message generation) that belong in a structured config, not interleaved with per-tool permission lists. Run `/lazy-core.agent-models` to fill and update it interactively. The scope rules are: entries under `_user.*` go to the global `~/.claude/lazy.settings.json`; entries under `_project.*` go to the project `.claude/lazy.settings.json`; plugin-domain groups go to the plugin's own install scope.

---

## What is safe to commit to git, and what should stay gitignored?

The tracked `settings.json` files (global `~/.claude/settings.json` and project `.claude/settings.json`) are for enablement-only entries: `enabledPlugins`, `enabledMcpjsonServers`, `hooks` registrations, non-secret `env` vars, model selection, and status-line config. Per-tool permission entries (`permissions.allow`, `permissions.ask`), `additionalDirectories`, and machine-specific `env` values belong in the gitignored `settings.local.json` files. Committing permission lists leaks your personal risk preferences to teammates who may have different policies. The `lazy-guard.settings` PreToolUse hook enforces this split by intercepting writes to settings files that violate it.

The same split applies to `lazy.settings.json[daemon].metrics`: the `enabled` flag and `repo_label` are tracked (they're a shared design decision), while the allocated port lives only in the gitignored local overlay, because a port that is free on one machine can be taken on another. `daemon.run_here` is the deliberate exception to "per-machine stays local" — it is a hostname-to-checkout-path map and lives in the **tracked** file on purpose, so the pairing travels to every clone (see the Dropbox/iCloud question below). `daemon.token_env` is tracked too — it only names an environment variable, never the token itself (see the next question but one).

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

No install-time question gates it anymore. `/lazy-core.install` always writes the flat `daemon` and `routines` sections into `.claude/lazy.settings.json`, creates `lazy.settings.json[experts]`, copies the `lazy.runtime.sh` shim to `.claude/bin/`, bootstraps `.experts/`, and registers the built-in `lazy-expert.pump` routine — the only precondition is that the current directory is (or can become) a git repo, since the runtime's tracked config and commits need one. All of it is driven by `/lazy-runtime.tick` just as well as by a background daemon, so none of it waits on a daemon to exist.

What is still opt-in is `daemon.enabled` — whether a background daemon actually supervises the project, versus you ticking it by hand. It is seeded `false` on first install, silently, with no wizard question: a project declares itself daemon-supervised by having the flag flipped, not by answering a prompt at install time. With it `false`, every routine, expert, and runtime artifact is already in place and runnable — `/lazy-expert.dispatch-job` and the rest of the `/lazy-expert.*` skills work immediately, and you drive routines and queued jobs by hand with `/lazy-runtime.tick`.

To make a project daemon-supervised, set `daemon.enabled: true` in the tracked `lazy.settings.json` and re-run `/lazy-core.install` — that is what unlocks the `run_here` question and the supervisor/metrics install described in the next two questions. A background daemon also needs its own `daemon.token_env` set before it will actually start — see the next question.

---

## Why does the runtime daemon refuse to start without `daemon.token_env` set?

A daemon is a standing background process, and every LLM call it makes has to spend under some account — with no name for that account, it would silently run on whatever account the machine happens to be logged into at that moment. `daemon.token_env` closes that gap: set it, in the tracked `<repo-root>/.claude/lazy.settings.json[daemon]`, to the name of an environment variable holding this daemon's own OAuth token (a plain string, e.g. `"CLAUDE_TOKEN_MYPROJECT"`). At startup the daemon resolves that variable — the real environment first, then a matching line in `~/.claude/.env` — and exports the result as `CLAUDE_CODE_OAUTH_TOKEN` to every job and routine it spawns afterward. Left absent, blank, or naming a variable that resolves nowhere in either source, the daemon exits immediately with an error naming what's missing, rather than starting anyway on the ambient login.

`/lazy-core.install` never seeds this key for you — add the token to `~/.claude/.env` (or the real environment) and point `daemon.token_env` at its variable name yourself before the daemon's first start. `/lazy-runtime.tick`, by contrast, needs no token: it is never a standing process, so it always runs under whichever account you are already using when you invoke it by hand.

Naming an explicit token also changes how the rate-limit guard scopes a closed subscription window: a raised window now only defers daemons spending under the *same* account (told apart by a digest of the exported token, or the machine login's account id when no token is set), so one project's daemon hitting its usage limit no longer freezes every other daemon sharing the host.

---

## Does `/lazy-core.install` set up monitoring for the runtime daemon?

Yes, but only on a project that is daemon-supervised (`daemon.enabled: true` — see the previous questions) and a checkout that actually runs the daemon locally. With the seeded default of `false`, install never reaches this step at all. Once `daemon.enabled` is true and the earlier `run_here` question confirms this machine and checkout are the pair on record, a later step asks once whether to enable the daemon's Prometheus `/metrics` endpoint — exposing routine ticks, errors, tokens, and queue depth on a loopback HTTP port for a Prometheus-compatible scraper. Answering "No" is recorded permanently and you are never asked again on that checkout; re-running `/lazy-core.install` reuses the recorded answer instead of re-asking.

Answering "Yes" allocates a free port sequentially starting from `9464` — reusing this checkout's already-recorded port on re-runs instead of picking a new one — and splits where the decision is written: the `enabled` flag and a human-readable `repo_label` (default: the folder name) go into the tracked `lazy.settings.json[daemon].metrics`, shared across machines, while the allocated port goes into the gitignored per-machine overlay, because a port that's free on one machine may be taken on another. The step then regenerates a host-wide Prometheus scrape-targets file so an external Prometheus with a `file_sd_configs` pointer picks up every locally running daemon with zero manual edits.

If the daemon later starts and finds its recorded port already taken by something else, it does not crash-loop — it records the conflict as an incident and keeps running without metrics until the conflict is resolved.

---

## My checkout is on Dropbox/iCloud/Syncthing and shows up on more than one machine — won't `run_here` start a daemon on all of them?

It would, if `run_here` only accepted `true`/`false` — but that shape is retired. `daemon.run_here` is now a hostname-to-checkout-path map, for example `{"nexus": "~/lazy-runtime/Money"}`, stored in the **tracked** `lazy.settings.json` so the pairing travels with the project to every clone (a gitignored overlay would never reach a machine that cloned the repo independently — exactly where a second daemon would appear). Neither half of the pair decides alone: the hostname says which machine, the path says which of that machine's checkouts drives the daemon — a single machine commonly holds more than one checkout of the same project (a working copy plus the one the daemon runs from), and naming only the host would collide between them the same way a bare `true` used to collide across synced machines. This question is only reached once `daemon.enabled` is `true` — see the questions above.

`/lazy-core.install` compares the map against the machine's own hostname (lowercased) and the checkout's own resolved path (symlinks included, so a symlinked path still matches). The named pair installs the supervisor as normal. Every other machine — and every other checkout on the named machine — both skips the supervisor install AND tears down any supervisor unit it already has for that checkout, so re-running `/lazy-core.install` anywhere that shouldn't be running the daemon self-heals a leaked one instead of leaving it running. The daemon itself also refuses to start on a checkout the map doesn't name, even while `daemon.enabled` stays `true`, so a leaked supervisor can't outlive the map even if you never get around to re-running install there. An empty map (`{}`) names nothing at all — the project stays daemon-enabled but nothing drives it until you point the map at a checkout.

Edit the map by hand — add or remove a `"<hostname>": "<path>"` entry — then re-run `/lazy-core.install` to apply it; entries recorded for other machines are left untouched. If the file still carries the retired shape (a bare boolean, or a plain list of hostnames from an install that predates the map), `/lazy-core.install` reports `run-here-invalid`, prints the offending value, and re-asks the question so your answer replaces it outright — the daemon refuses to start until the map is in the current shape.

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

## I dispatched a job to the wrong expert (or the requirements changed) — how do I stop it?

Run `/lazy-expert.cancel-job <expert> <job_id>`. If the job is still running, it sends SIGTERM (then SIGKILL after a grace period) to the executor's process group and marks the bundle `CANCELLED`; if it's already `done`, you're asked whether to mark it cancelled anyway. Either way nothing on disk is deleted — the job directory (request, response, transcript, result) stays for forensics and ages out through the normal failed-job cleanup window. Cancelling also releases the job's dedup key, so a fresh dispatch with the same key creates a brand-new job rather than getting silently deduplicated against the cancelled one. A job that's already cancelled, or one whose directory no longer exists, is reported as such with no further action taken.

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

## Why does the expert-spawn sandbox now record `allowUnsandboxedCommands: false`?

A confined spawn is only as strong as what happens when the sandbox actually blocks something. Claude Code's own default for an absent `allowUnsandboxedCommands` key is `true`, and under that default a command the sandbox refuses on its first try is simply retried unsandboxed — subject only to the ordinary permission check, which the bare `Bash` allow entry every expert spawn already carries in `settings.local.json` passes without a prompt. In practice this meant a confined spawn could still write or delete outside its `allowWrite` scope on the second attempt, even though the first attempt was correctly blocked.

`lazycortex-core sandbox-sync` now writes `allowUnsandboxedCommands: false` into `.runtime/sandbox.settings.json` whenever the key is absent, closing that retry path — it never touches a value already on record, so a `true` you (or an earlier install) set deliberately is left as your call, not silently reversed. `/lazy-core.audit` and `/lazy-runtime.preflight` both `[FAIL]` on a missing or `true` value now, and either finding points at the same fix: `lazycortex-core sandbox-sync --repo-root "$PWD"`.

---

## When does the runtime daemon halt, and how do I recover it?

The daemon halts in three distinct situations. A **working-tree halt** (`uncommitted_changes`) happens when a routine or expert job leaves the repo in a dirty state — the daemon stops rather than proceeding with uncommitted changes in the tree. A **remote-sync halt** (`git_pull_diverged`, `git_push_failed`, `git_remote_unavailable`) happens when the daemon's pre- or post-tick git sync fails against the actual remote — a genuine divergence between local and origin, exhausted push retries, or stderr that names an unreachable network or host. A **local-sync halt** (`git_local_failed`) happens when that same git sync fails for a purely local reason instead — a held `index.lock` past its retry backoff, a bad ref, or a checkout-permission problem; a transient `index.lock` race (an expert job committing at the same moment, say) is retried in place with backoff before it is ever allowed to halt, so this reason only fires once that retry is exhausted.

Run `/lazy-runtime.recover` to unblock it. For working-tree halts the skill walks you through four options: commit the dirty files (you supply the message), stash them, discard them, or abort and leave the halt in place. For remote- and local-sync halts the skill surfaces reason-specific guidance (the exact git commands to inspect and fix the divergence, push failure, or local git problem) and waits for you to confirm you have resolved the situation before clearing the halt block. Once the halt block is cleared from `.runtime/state.json`, the daemon resumes on its next iteration.

If the cleanup does not produce a clean tree, the skill reports "working tree still dirty; refusing to resume" and leaves the halt intact — inspect with `git status` and re-run the skill.

---

## An expert I wired into a routine keeps timing out or never responds — how do I find out why before it burns another wall-timeout?

Run `/lazy-runtime.preflight [<expert-name>]` before wiring a new expert or MCP server into a live routine, or as soon as one starts behaving this way. It validates every routine-attached expert without doing any real work: static checks first (unresolvable agent, missing aspect or protocol, a bad `mcp_config` path), then — unless you pass `--no-probe` for a faster structural-only sweep — an actual headless launch with a trivial prompt, using the same command line the pump itself would use, so a hanging MCP server or an auth prompt that would otherwise eat the routine's timeout shows up here in seconds instead.

The report leads with checkout-level findings that apply to every expert — most importantly a shared inbox another daemon on the same host is already draining, which the skill can't auto-fix (you decide which project keeps that `daemon.run_here` entry), and a sandbox allowlist that doesn't cover a symlinked path, which it can. Per expert it then renders a verdict, static issues, and each MCP server's status (connected / timed-out / auth-required / spawn-failed / pending-approval). For anything it can fix — dropping a broken MCP server from an expert's config, repairing a sandbox path, correcting a bad `mcp_config` path — it asks you one `AskUserQuestion` at a time before applying anything; a server that needs interactive login gets you the exact `claude mcp login` command to run by hand instead, since a headless daemon spawn has no TTY to authenticate through.

---

## Can I trigger my own automation when the daemon pushes?

Yes. Set `daemon.git.post_push_hook` to a shell command in the `daemon.git` block of `lazy.settings.json`. It fires immediately after the daemon's post-iteration push actually advances `origin/<base_branch>` — whether that push was a plain fast-forward or the result of a post-rebase retry — with `LAZY_PUSH_REPO` (absolute repo path), `LAZY_PUSH_BRANCH`, `LAZY_PUSH_REMOTE`, `LAZY_PUSH_OLD_SHA`, and `LAZY_PUSH_NEW_SHA` set in the hook's environment. That is enough to trigger a deploy, post a notification, or kick off any other automation keyed to what the daemon just pushed.

The hook is fully isolated from the daemon's own tick: a non-zero exit, a timeout past `post_push_timeout_sec` (30 seconds by default), or a spawn failure is journaled and never halts the daemon, retries the push, or fails the tick. It also never fires when nothing was actually pushed — an in-sync tick, the already-published fallthrough, and a discarded rebase-conflict retry all skip it. This only applies when `daemon.git.remote_sync` is `"pull_push"`; a `"pull"`-only daemon never pushes, so the hook never fires.

If the hook's own job is fanning those commits out into other local checkouts of the same repo — a second clone, a Dropbox-synced sibling — pull with the daemon's own `safe-pull <repo-dir> <remote> <ref> [--timeout-sec N]` primitive rather than a bare `git pull`; it is exactly what the daemon's own post-push fan-out is built to pair with. It waits out a held `index.lock` in the target checkout, refuses to touch an index that already carries staged content, and merges only a strict fast-forward — every guarded outcome (a timed-out wait, staged content in the way, a non-fast-forward) exits `0` with a JSON `{"outcome": ...}` result instead of failing your hook script, so it can never leave the kind of index residue a racing bare `git pull` would.

---

## If publishing a routine's commits hits a rebase conflict, do I lose work from other routines that ran in the same tick?

No. The daemon publishes right after each routine that moved `HEAD`, not once at the end of the whole tick — so by the time a later routine's push conflicts, every earlier routine in that same tick has already landed on origin. A conflict discards only the offending routine's own unpushed commits (`git rebase --abort && git reset --hard origin/<base_branch>`), and that discard is not a halt — the routine simply re-runs on its next scheduled tick, on top of whatever the operator pushed in the meantime.

The discard also winds back two side effects the discarded commits carried, so nothing is silently lost: any expert job whose `CONSUMED` marker only landed in the discarded range gets that marker removed again (tracked in `.runtime/consumed-unpushed.log`), so `/lazy-expert.collect-job` sees it as pending and the daemon lands the result again instead of retiring a result that never actually reached origin; and any `git`-routine's `last_seen_sha` cursor that only the discarded commits advanced past is rewound to the merge-base with origin, so that routine rescans from the last published commit rather than skipping events it only thought it had handled. If git itself can't determine whether a cursor is still reachable after the discard, the daemon leaves that cursor as it stands, logs a `cursor_probe_failed` incident against the routine, and resolves the incident automatically on the routine's next clean tick.

---

## How do I run routines and drain queued jobs on a checkout without a live daemon?

Run `/lazy-runtime.tick [<routine-name>] [--drain]`. It runs the daemon's own primitives by hand, in the daemon's own serial order, on a checkout whose daemon is not running — including a checkout where `daemon.enabled` has never been flipped to `true` at all, since routines and experts install unconditionally (see the runtime-opt-in question above). With no arguments it runs a single iteration — every due routine in priority order, then at most one READY job through the pump (the daemon's own single-spawn ceiling). `--drain` repeats iterations, sleeping between them exactly as the daemon would, until nothing is due and the queue is empty — it stops early on a halt, a dirty tree, a raised rate-limit flag, or a pass that made no progress. Naming a routine runs only that one, ignoring both its interval and `--drain`.

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

All five require a dot-namespaced `name` (e.g. `acme-lint.tick`). The wizard in `/lazy-routine.register` asks for the type first, then prompts only for the fields that type needs. Registration itself never depends on `daemon.enabled` — a routine registered on a project ticking by hand (see the runtime-opt-in question above) is picked up the next time you run `/lazy-runtime.tick`, exactly as it would by a live daemon.

---

## How do I stop a routine, and can I just re-register it with different settings?

Run `/lazy-routine.unregister <name>` to remove it from the flat `routines` section for good — it's idempotent, so unregistering a name that isn't registered is a harmless no-op reported `already-absent`, not an error. You can't just re-run `/lazy-routine.register` with a new shape over an existing name: register refuses to overwrite an existing entry unless you pass `--force`. Unregister first, then register the new shape.

The one name it won't remove without a fight is the built-in `lazy-expert.pump` — the routine that drains the expert job queue. Unregistering it aborts unless you pass `--force`, and even then the skill prints a warning that expert jobs stop processing until you re-register the routine or re-run `/lazy-core.install`.

---

## What are "optional protocols" on a routine, and how do I attach one?

A routine that dispatches expert jobs (any type carrying an `expert` + `request` pair) can carry a `protocols` list — reference documents its writers may consult. The routine's own install or configure step already seeds whatever protocols are mandatory for it; those are fixed by design and never touched again. `/lazy-routine.offer-protocols --routine <name> --context "<one line describing what the writers produce>"` is how you attach anything beyond that: it discovers every reference file flagged as a protocol candidate across your installed plugins, judges each one against your one-line context, and only asks about the ones that are actually relevant — you never see the whole candidate pool. Pick zero or more via a multi-select prompt; the chosen ones are unioned into the routine's existing `protocols` list, idempotently.

This is an operator-invoked skill only — no install or configure flow dispatches it, since a system routine's protocol set is fixed by design. If it reports `no-relevant-candidates`, nothing in the discovered pool matched your stated context; if it reports `routine-absent`, the named routine isn't currently registered.

---

## What happens if I register a routine whose `inbox_dir` is not gitignored?

`/lazy-routine.register` checks this for `inbox`-type routines using `git check-ignore`. If the directory is tracked rather than gitignored, the skill warns you: an inbox routine moves files between iterations, which dirties the working tree and triggers the daemon's halt protection on every cycle. You get three options — add the directory to `.gitignore` now (recommended), continue anyway and commit moves manually, or abort the registration. If you choose to add it, the skill appends the entry to `.gitignore` but does not auto-commit; you commit when you are ready to coordinate with other in-flight changes.

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

## Does `/lazy-core.install` write my agent-model tiers and templates for me, or do I have to run something separately?

Both happen automatically as part of install, through two skills you never invoke directly. `lazy-core.agent-models-seed` is dispatched by every plugin's own install skill to seed that plugin's curated model tiers (haiku/sonnet/opus) into `agent_models.lazycortex` in `lazy.settings.json`, reading the tier values from `lazycortex-core`'s own `default-tiers.json`. It never overwrites a tier you already set by hand — an existing value is left alone and reported `kept-local`. `lazy-core.scaffold-sync` is dispatched the same way to copy a plugin's authoring templates into your `.claude/templates/<group>/` directories and register their path globs in `lazy-core.scaffold.md`, overwriting a stale copy of a plugin-owned template on every re-run (a template you want to customize belongs in a `_local` entry instead — see the next question — not a hand-edited copy of the plugin's own file).

Both are idempotent and silent when there is nothing new to seed. If either fails because `lazycortex-core` itself is not installed or its `default-tiers.json`/CLI is missing, the reporting install skill surfaces that as a step failure rather than continuing silently.

---

## Does `/lazy-core.install` connect my experts to alternative LLM providers automatically?

Only if you ask it to, and only once. If no `providers` block exists yet (tracked or in the gitignored local overlay), install asks a single yes/no question: connect one or more non-Anthropic endpoints for expert jobs now, or skip and add them later. Answering "No" writes nothing — every expert job keeps running against the Anthropic default with no provider entry at all, since providers are opt-in. Answering "Yes" walks you through naming provider(s) and dispatches `/lazy-core.providers add <name>` for each, which is the same wizard you'd run by hand. If a `providers` block already exists in either the tracked file or the local overlay, install skips the question silently and leaves your existing entries alone.

Once install has asked (either answer), it never asks again — reach for `/lazy-core.providers add <name>` yourself any time later to connect a provider you skipped at install time.

---

## What is `/lazy-core.providers` for, and what does it check before writing an entry?

It manages the `providers` block: named LLM endpoints (base URL, credential env var, a four-tier model map for `fable`/`opus`/`sonnet`/`haiku`) that an expert's own `provider` field in `lazy.settings.json[experts]` can point at instead of the Anthropic default. Because a provider entry is a machine fact — a specific endpoint and a specific credential name — it's written only to the gitignored `.claude/lazy.settings.local.json`, never the tracked settings file; the skill refuses to write at all if that local overlay isn't gitignored.

Before writing an `add` or `update`, it runs the same structural validation the runtime's own dispatch-time resolver applies — so a wizard-approved entry can never diverge from what actually works at spawn time — plus a token-presence check (the named environment variable must resolve via the real environment or `~/.claude/.env`) and a liveness probe (`GET <base_url>/v1/models` with the resolved token must return `200`). Any failing check aborts with no write. Run `/lazy-core.providers list` any time to see registered entries and their source (`tracked` entries are flagged as a WARN — they belong in the local overlay instead).

---

## Why did `/lazy-core.doctor` flag one of my providers, and what do the different findings mean?

`/lazy-core.doctor` re-runs the same validation `/lazy-core.providers` applies at write time against every entry currently on record, so a provider that passed the wizard once but was later hand-edited (or whose upstream requirements changed) doesn't go unnoticed. `provider_unknown` (FAIL) means an expert's `provider` field names something not in the merged `providers` block — register the provider or fix the expert's entry. `provider_endpoint_incomplete` (FAIL) means `base_url` or `token_env` is missing or blank. `provider_tier_gap` (FAIL) means the `models` map is missing one of the four required tiers. `provider_claude_literal` (FAIL) means a tier value is a `claude-*` model name, which can't pass through a foreign endpoint. `provider_reserved_route` (FAIL) is specific to the `openai` provider — its tiers must be prefixed `rt-openai/` rather than routed as a bare `openai/*` interactive key. `provider_token_missing` (WARN, non-blocking) means the named credential variable doesn't currently resolve in the environment or `~/.claude/.env` — the entry is still structurally valid, but a job dispatched against it will fail at spawn time until the variable is set. Fix any of these by re-running `/lazy-core.providers update <name>`, which re-validates before writing.

A provider-bound expert job never receives your own Anthropic credentials — every job dispatched against a provider strips `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_API_KEY` from its spawn environment before the provider's own token is set, so neither of your Anthropic credentials can travel to a foreign endpoint.

---

## How do I add a template for my own repo-specific file type?

Run `/lazy-core.scaffold-local` rather than hand-editing the registry in `.claude/rules/lazy-core.scaffold.md` — that file's plugin-owned entries are `lazy-core.scaffold-sync`'s territory (see the previous question), and the reserved `_local` key is where repo-specific entries live instead. The wizard asks for a `group` (the subdirectory under `.claude/templates/`), a `kind` (the template name), and — for `mode=add` — a list of glob patterns that should start from this template; it creates the template file at `.claude/templates/<group>/<kind>-template.md` if it doesn't exist yet and upserts the registry entry. `mode=remove` deletes both the entry and its template file after confirming it exists. A `_local` entry wins over a plugin-shipped entry at equal glob specificity, so this is also how you override a plugin's own template for one path pattern.

---

## Which skills support `--dry-run` and what does it do?

Two skills covered in this block accept `--dry-run`:

- `/lazy-core.setup` — builds and previews the install plan (which skills would run, in what order) without executing any of them. The settings migration step (Step 0) still runs in dry-run mode so the preview reflects the post-migration state.
- `/lazy-core.agent-models` — walks the wizard and reports what tier assignments would be written, without touching either `lazy.settings.json` file.

In both cases, `--dry-run` is purely read-only: no files are created or modified, and the skill exits after the preview. It is safe to run at any time and does not require undoing anything afterward.

---

## When should I reach for `/lazy-core.iterate` instead of just fixing things by hand?

`/lazy-core.iterate` is for a bounded do-verify-fix loop: fixing round after round against a single automatic verification (a test suite, an audit, a spec read) until nothing is left to fix, or one of six stop conditions catches a run that would otherwise loop forever. Reach for it when the target is a single file/spec/test-suite/diff, "clean" has a concrete verification you can name up front, and the fixes are the kind you'd do in a loop anyway — not for a one-off fix where you already know the exact change.

Before the loop starts, it locks three things: the **target** (a concrete file, PR, spec, or test-suite — never a vague topic), the **done-state** (what "clean" means — zero issues, no FAIL findings, all tests passing), and the **verification action** (the exact command or read that produces an issue list each cycle). All three are asked via `AskUserQuestion` if not already clear from your request.

The loop then runs verify → decide → fix cycles under six stop conditions, checked in priority order every cycle: a hard cycle cap (default 5), a clean run (success), a severity floor (stop once only minor findings remain), repeat detection (the same issue survives a fix attempt twice in a row — stop and escalate rather than keep guessing), a regression spiral (a cycle makes more new issues than it resolves — stop and suggest a revert), and an optional budget. These caps exist so the skill cannot run away chasing a target that isn't converging; it reports what was fixed, what remains, and which condition stopped it.

---

## Why does `git commit` now refuse a bare commit and ask me to name paths?

The git-guard hook's default behavior changed: **pathspec discipline** is now the default mode (`lazy.settings.json["git"]["pathspec_enabled"]` defaults to `true`), and it replaces the staging-window mutex as what most sessions actually hit. Under pathspec discipline the shared git index is treated as the operator's own space — a Claude session never leaves content parked there for a later commit to accidentally sweep up. Concretely: a bare `git commit` (or `-a`/`-am`/`.`/`:/`/a directory pathspec) is refused; every commit must name explicit paths, e.g. `git commit -m "..." -- <path> <path>`. A new file is registered with `git add -N <path>` (no content staged) rather than a plain `git add`; renames and deletes go through Bash `mv`/`rm`, never `git mv`/`git rm` (both auto-stage); `git reset` still works normally if something needs un-parking. The only exceptions are a bare commit mid-merge (git itself refuses a partial commit there) and `--amend` when a pathspec is given or the index is already clean.

If a session's own tooling staged content for you (a skill, a pre-commit pipeline step), fold the paths it reports into your commit pathspec rather than falling back to a bare commit. You don't need to change anything to opt in — the hook enforces the new default and tells you the pathspec form to use whenever it refuses a bare commit.

---

## Why did my commit get denied even though I named explicit paths?

Naming paths is necessary but not sufficient under pathspec discipline — a session commit also requires an index that is otherwise clean. A session never stages content itself, so anything already sitting in the index belongs to someone else: the operator's parked work, an intentional `git rm --cached` untrack, or (rarer) a shared index left in a bad state by an earlier failed partial commit. When a commit fires and finds staged content, the hook polls briefly — 15 seconds by default, overridable via the `LAZYCORTEX_GIT_GUARD_WAIT_SECONDS` environment variable — in case the dirt is just the tail end of the operator's own staging burst, then denies if it's still there once the window closes.

The denial deliberately does not prescribe a fix, because a session has no way to tell the three causes apart: stop and escalate to the operator, and do not retry until `git diff --cached` comes back empty. Never run `git reset` on the operator's behalf to clear the way. Intent-to-add registrations (`git add -N <path>`, the only kind a session may create) never count as staged content and never trigger this denial.

Separately, if a commit succeeds but the index is non-empty again immediately afterward — even though it started clean — that is the signature of a partial commit's temporary index getting written into place as the real one, typically from a crash or a race mid-commit. The hook raises an ALARM for this case instead of blocking, since the commit already landed; surface it to the operator, who runs `git reset` to rebuild the index from `HEAD` (worktree untouched) — never something a session does on its own.

The same index-health check also watches `pull`, `merge`, and `rebase`, not just `commit`. When the staged content it finds afterward is a **lagging index** — every staged path's worktree file already matches `HEAD`, meaning an index write simply lost a race to a fast-forward — it alarms with that specific diagnosis rather than the generic swap message, because that signature is provably lossless rather than ambiguous. The runtime daemon applies the same check to its own pre-tick pull and repairs a proven-lossless lagging index automatically with `git reset`, journaling the repair; anything that isn't provably lossless is left alone for the operator, exactly as a session would.

---

## `git status` briefly showed staged content nobody staged, right after a Dropbox/iCloud sync, and then it cleared on its own — what happened?

That is a sync-displaced index healing itself, not a swap the git-guard hook needed to alarm on. A cloud-sync client (Dropbox, iCloud, Syncthing) can race git's own atomic rename of `.git/index`, lose, and resolve the "conflict" by leaving an older index under the real name while parking the version git actually wrote last beside it as `index (<owner>'s conflicted copy <date>)`. The resurrected old index is what makes `git status` show phantom staged content.

`/lazy-core.install` registers a `lazy-core.index-guard` routine alongside the built-in expert pump and doctor tick — it runs every 5 minutes, independent of `daemon.enabled`, and `/lazy-runtime.tick` drives it on a checkout with no daemon exactly as it would any other routine. The git-guard hook also runs the same heal as a pre-flight check on every commit-related tool call. Either way, the heal decides by content against `HEAD`, never by file timestamp: it restores the newest conflicted copy over the live index only when that copy carries a valid index signature, differs from the live index, and stages nothing beyond `HEAD` (the copy is the one git actually wrote last, and a live index that disagrees with `HEAD` is the resurrected stale one). A copy that itself disagrees with `HEAD` while the live index also disagrees is two staged states nothing here can rank — both are left in place for the operator, reported `skipped: ambiguous`. No `index.lock` may be present either — a git operation mid-flight is left alone and retried on the next pass. The worktree, `HEAD`, and refs are never touched, and a repository with no conflicted copies is a silent no-op.

Because the heal runs automatically on this cadence, you should rarely see the phantom state persist past a minute or two. If you want to trigger it immediately rather than wait for the next tick, run `/lazy-runtime.tick lazy-core.index-guard`. Separately, both the daemon and `/lazy-runtime.tick` now run their own git calls with `GIT_OPTIONAL_LOCKS=0`, so a background `git status` they perform no longer rewrites the shared index on every pass — fewer index rewrites means fewer chances for a sync client to race one in the first place.

---

## What is the git staging lock, and when do I need to touch it?

The staging-window mutex is the previous default and is now dormant on a fresh install — it only takes over when you flip `lazy.settings.json["git"]["pathspec_enabled"]` to `false` and `["mutex_enabled"]` to `true`. In that mode, multiple Claude Code sessions sharing one checkout serialize the staging window — from the first `git add` that makes the index non-empty to the `git commit` that empties it again — so only one session stages at a time, with the same auto-break heuristics as before (holder process dead, on a different host, or idle for a while).

`/lazy-core.git-status` and `/lazy-core.git-unlock` only have something to act on under mutex mode; on the pathspec-discipline default no session ever opens a staging window, so there is nothing to inspect or break. Run `/lazy-core.git-status` to check the lock (holder, age, liveness, whether it's currently breakable) without changing anything, and reach for `/lazy-core.git-unlock` — which asks for confirmation before deleting the lock file — only when status shows a lock the automatic heuristics won't break on their own. Setting `lazy.settings.json["git"]["enabled"]` to `false` silences the hook entirely, in either mode.
