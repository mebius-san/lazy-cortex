---
chapter_type: walkthrough
summary: Bootstrap the per-repo runtime daemon and know how to recover it with /lazy-runtime.recover from any of its halt reasons — dirty tree, remote sync, bad routine config, or a closed rate-limit window.
last_regen: 2026-08-21
diagram_spec:
  anchor: "How setup and recovery connect"
  request: "Sequence diagram showing three phases: (1) User runs /lazy-core.install, answers yes to the runtime-daemon wizard, wizard writes .claude/bin/lazy.runtime.sh + lazy.settings.json[experts] + flat daemon and routines sections; (2) User runs .claude/bin/lazy.runtime.sh, daemon starts and polls .experts/.jobs/ on interval, user checks .runtime/state.json for a recent last_run; (3) Working tree goes dirty, daemon writes daemon_halted to .runtime/state.json, user runs /lazy-runtime.recover, skill shows halt context, user picks a cleanup mode (commit/stash/discard), skill clears daemon_halted, daemon resumes on next iteration."
  kind_hint: sequence
source_skills:
  - lazy-core.install
  - lazy-runtime.recover
source_sha: 8e1778242c1d07b5ae5e6fee24b46b72873fefdc
---
# How do I bootstrap the runtime daemon and recover it if it halts?

The expert runtime gives you a serial, per-repo daemon that drains a job queue and runs registered plugin routines. Getting from zero to a daemon that runs in the background is a short journey: install and start it, confirm every registered expert is actually launchable, confirm the daemon is polling, then know how to unblock it if it halts — from a dirty working tree, a failed remote sync, a routine config gone invalid, or a closed subscription rate-limit window.

## Outcome

After completing this walkthrough you have a running runtime daemon that polls for expert jobs and registered routines on a regular interval, confidence that its registered experts will actually launch when a routine dispatches them, and a working recovery path for every halt reason the daemon can raise.

## What you need

- `lazycortex-core` enabled in `~/.claude/settings.json` and the plugin cache populated (run `/plugin update lazycortex-core@lazycortex` if you have not already).
- A git repository — the runtime is project-scoped and writes state under `.runtime/` and journal logs under `.logs/lazy-core/runtime/`.
- Python 3.12 or later on your `$PATH` — the daemon and all runtime scripts are Python.

## The journey

### Step 1 — Install and start the daemon

Run `/lazy-core.install` inside the repo and answer **Yes** to the runtime-daemon wizard. The wizard's full sequence — what it writes to `lazy.settings.json`, the expert-discovery scan, the daemon-supervisor offer, the expert-spawn sandbox question, the git-guard flags it now seeds into `lazy.settings.json` (`git.enabled`, `git.pathspec_enabled`, `git.mutex_enabled`), and the optional Prometheus metrics endpoint — is covered in the **Install, audit, and maintain lazycortex-core** block chapter; work through Steps there before continuing here. Come back once the wizard has finished.

If this repo declares externally-sourced working directories (e.g. a shared inbox it does not carry in git) via `external_dirs.paths`, the wizard resolves them before it touches the supervisor. On a fresh checkout it asks once where they live on this machine and remembers the answer for every future run. It also refuses to install a supervisor when two checkouts would end up driving the same physical inbox directory — it names the other checkout and asks you to set `daemon.run_here: false` on one of them before continuing.

If you chose a supervisor during install, the daemon is already running — skip to Step 2. Otherwise start it by hand from the repo root:

```
.claude/bin/lazy.runtime.sh
```

The daemon reads the flat `daemon` and `routines` sections of `lazy.settings.json`, runs the `lazy-expert.pump` routine on each polling iteration, drains any `READY` jobs it finds, and loops. One daemon per repo means no two routines ever contend over the working tree or git state.

### Step 2 — Confirm every registered expert is actually launchable (verification gate)

Before you trust the daemon with real routine dispatches, run:

```
/lazy-runtime.preflight
```

The skill emulates a real launch for every routine-dispatched expert — resolving its agent, aspects, and protocols, and initializing its optional MCP servers — with a trivial prompt that does no real work, then renders a per-expert verdict table. A config that looks fine on paper (a typo'd agent name, an MCP server that hangs at init, a missing model pin) fails silently at runtime otherwise: the job just eats the routine's wall timeout and dies with nothing but a stuck queue entry to show for it.

If an expert fails, the skill walks you through one fix at a time — dropping a misbehaving MCP server, correcting a bad config path, or pinning a model tier — and only writes anything after you confirm. Re-run `/lazy-runtime.preflight` until every expert shows `ok` before moving on.

### Step 3 — Verify the daemon is polling (verification gate)

After one polling interval, open `.runtime/state.json` and confirm the `last_run` timestamp is recent. If the timestamp is absent or stale, check that the shim is executable (`ls -l .claude/bin/lazy.runtime.sh`) and that Python 3.12+ is on your `$PATH`.

### Step 4 — Recover if the daemon halts

The daemon halts on one of several named reasons and writes a `daemon_halted` block to `.runtime/state.json` in every case. If you notice jobs stop processing, run:

```
/lazy-runtime.recover
```

The skill reads the halt context and shows you `triggered_by` (which routine or `lazy-expert.pump` caused the halt), `expert` + `job_id` (when the halt came from inside an expert job), and `reason` (the halt family).

**Working-tree halt (`uncommitted_changes`)** — a routine or expert left uncommitted changes behind. The skill also shows `dirty_paths` (the captured `git status --porcelain` output) and asks how to clean up before resuming:

- **commit** — stages everything and commits with a message you provide. Use when the dirty changes are intentional work you want to keep.
- **stash** — runs `git stash push -u`. Tucks the dirt away so you can restore it manually later.
- **discard** — runs `git checkout -- . && git clean -fd`. Throws away every dirty change. This is irreversible.
- **abort** — leaves everything as-is and exits. The daemon stays halted until you clean up manually and re-run the skill.

**Remote-sync halts (`git_pull_diverged` / `git_push_failed` / `git_remote_unavailable`)** — the daemon's pre- or post-tick remote sync (configured via the `daemon.git` block in `lazy.settings.json`) hit an unrecoverable state. Before you ever see this halt, the daemon retries on its own with backoff whenever a remote-touching operation looks merely unreachable (a network blip, a DNS hiccup) — so a brief outage no longer halts the daemon at all; `git_remote_unavailable` now only fires once those retries are exhausted. The skill does not attempt to fix these automatically (automatic resolution could silently drop your commits). Instead it surfaces reason-specific guidance — for example, inspecting `git log --oneline HEAD origin/<branch>` for a diverged branch, or checking network and `git remote -v` for a remote-unavailable halt. After you resolve the situation by hand, confirm **resume** to clear the halt block. The daemon's next tick re-evaluates; if the condition persists it will halt again with the same reason.

**Routine-config halt (`routine_config_invalid`)** — a `routines.<name>` entry in `lazy.settings.json` (or its gitignored `.local.json` overlay) no longer matches its type's schema, so the daemon dropped the routine and stopped rather than silently running on a config it can't trust. The daemon never auto-corrects a rejected entry — an unknown field may be a typo, a leftover of an older schema, or intent the schema hasn't grown to cover yet, and only you know which. The skill points you at the schema error (`lazycortex-core error-list`, or the newest `.logs/lazy-core/runtime/<date>.jsonl` record whose `name` matches the routine) so you can fix the entry by hand or re-register it with `/lazy-routine.register --force`. Confirm **resume** once the entry is valid again.

**Rate-limit halt (`rate_limit`)** — the host-local subscription rate-limit window closed, and the daemon paused rather than burn a spawn against it. Nothing is broken here and no git repair is needed — the daemon lifts this halt itself the moment the window reopens (the skill shows you `resets_at`, the epoch second that happens). Confirm **resume** only if you want the queue moving again before then; the pump's pre-spawn check still refuses to spawn while the shared rate-limit flag holds a live record, so resuming early burns no tokens.

Once cleanup or manual repair succeeds and the tree is clean, the skill atomically clears the `daemon_halted` block from `state.json`. The daemon resumes scheduling on its next iteration with no restart required.

If the tree is still dirty after cleanup (e.g., a submodule left additional changes), the skill reports `still-dirty` and leaves the halt block in place. Run `git status` to inspect, resolve the remaining changes, and re-run `/lazy-runtime.recover`.

## After you're done

The daemon runs continuously, draining jobs and firing registered routines. The built-in `lazy-expert.pump` routine processes them serially per expert so there is never contention. An autonomous `lazy-runtime.doctor` routine runs hourly and handles DEAD expert jobs automatically — retrying recoverable failures and permanently failing jobs the daemon can no longer make progress on — without requiring operator action.

Whenever you wire a new expert into a routine, or a routine's expert spawns start timing out, re-run `/lazy-runtime.preflight` before trusting the daemon with it again — catching a broken spawn config at preflight time is far cheaper than debugging a stuck queue entry after the fact.

If your `daemon.git` block sets `remote_sync: "pull_push"` and you also want automation to fire the moment the daemon's work actually lands on `origin` — a deploy hook, a notification, waking a device to pull — set `daemon.git.post_push_hook` to a shell command. It runs after every push that advances the branch (fast-forward or post-rebase), with the push context available in `LAZY_PUSH_REPO`, `LAZY_PUSH_BRANCH`, `LAZY_PUSH_REMOTE`, `LAZY_PUSH_OLD_SHA`, and `LAZY_PUSH_NEW_SHA` environment variables. The hook is crash-isolated: a non-zero exit, a timeout past `post_push_timeout_sec` (30 seconds by default), or a spawn failure is journaled but never halts the daemon, retries the push, or fails the tick — it also never fires on a tick where nothing was actually pushed.

If you opted into the metrics endpoint during install, the daemon exposes runtime health (routine ticks, errors, tokens, queue depth) on the allocated loopback port for a Prometheus-compatible scraper — nothing further to do here, it runs alongside job draining with no separate startup step. If another daemon on the same host already holds that port, this daemon does not crash-loop over it — it records a `metrics_port_conflict` incident naming the current holder and keeps draining jobs with metrics simply unavailable until the port frees up or you reinstall to pick a fresh one.

Most halt reasons are expected operational events, not errors in the daemon itself — a rate-limit window closing is normal subscription throttling, and it clears itself. When `uncommitted_changes` fires often from a particular routine, that routine's output logic is leaving dirt behind — investigate there, not in the daemon.

## How setup and recovery connect

```mermaid
%%{init: {'themeVariables':{'background':'transparent','primaryColor':'#1e3a5f','primaryBorderColor':'#4a90e2','primaryTextColor':'#fff','lineColor':'#4ae290','actorBkg':'#1e3a5f','actorBorder':'#4a90e2','actorTextColor':'#fff','actorLineColor':'#4a90e2','signalColor':'#4ae290','signalTextColor':'#000','noteBkgColor':'#5f4a1e','noteBorderColor':'#e2a14a','noteTextColor':'#fff','labelBoxBkgColor':'#5f4a1e','labelBoxBorderColor':'#e2a14a','labelTextColor':'#fff','loopTextColor':'#e2a14a'},'sequence':{'diagramPadding':5,'useMaxWidth':true}}}%%
sequenceDiagram
  participant user as User
  participant wizard as Install Wizard
  participant daemon as Runtime Daemon
  participant recover as Recovery Skill

  Note over user,wizard: Phase 1 - install and wizard setup
  user->>wizard: run /lazy-core.install
  wizard->>user: prompt runtime-daemon wizard
  user->>wizard: answer yes
  wizard-->>user: writes .claude/bin/lazy.runtime.sh, lazy.settings.json experts, daemon and routines sections

  Note over user,daemon: Phase 2 - daemon polling
  user->>daemon: run .claude/bin/lazy.runtime.sh
  daemon-->>user: daemon started, polling .experts/.jobs on interval
  user->>daemon: check .runtime/state.json
  daemon-->>user: last_run is recent

  Note over daemon: Phase 3 - halt and recovery
  daemon->>daemon: working tree goes dirty, writes daemon_halted to .runtime/state.json
  user->>recover: run /lazy-runtime.recover
  recover-->>user: shows halt context
  user->>recover: picks cleanup mode - commit, stash, or discard
  recover-->>daemon: clears daemon_halted
  daemon-->>user: resumes on next iteration
```
