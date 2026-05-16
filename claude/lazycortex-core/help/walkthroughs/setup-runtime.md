---
chapter_type: walkthrough
summary: Bootstrap the per-repo serial daemon so the async expert team has an executor — install wizard, start the daemon, then unblock it with /lazy-runtime.recover if the working tree halts.
last_regen: 2026-05-16
diagram_spec:
  anchor: "How setup and recovery connect"
  request: "Sequence diagram showing three phases: (1) User runs /lazy-core.install, wizard asks about runtime, user opts in, wizard writes .claude/bin/lazy.runtime.sh + lazy.settings.json[experts] + lazy-core.runtime block; (2) User runs .claude/bin/lazy.runtime.sh (daemon starts, polls .experts/.jobs/ on interval); (3) Working tree goes dirty, daemon writes daemon_halted to .logs/lazy-core/runtime/state.json, user runs /lazy-runtime.recover, skill shows halt context, user picks cleanup mode (commit/stash/discard), skill clears daemon_halted, daemon resumes on next iteration."
  kind_hint: sequence
source_skills:
  - lazy-core.install
  - lazy-runtime.recover
---
# How do I bootstrap the runtime daemon and recover it if the working tree halts?

The expert runtime gives you a serial, per-repo daemon that drains a job queue and runs registered plugin routines — without hitting Claude Code's subagent nesting limit. Setting it up takes three actions: run the runtime-daemon wizard inside `/lazy-core.install`, start the daemon with `.claude/bin/lazy.runtime.sh`, and know how to unblock it with `/lazy-runtime.recover` if a job or routine leaves the working tree dirty or a remote-sync operation fails.

## What you need

- `lazycortex-core` enabled in `~/.claude/settings.json` and the plugin cache populated (run `/plugin update lazycortex-core@lazycortex` if you have not already).
- A git repository — the runtime is project-scoped and writes state under `.logs/lazy-core/runtime/`.
- Python 3.12 or later on your `$PATH` — the daemon and all runtime scripts are Python.
- At least one agent file with an `expert_protocol:` frontmatter field somewhere the wizard can discover it (plugin cache, `~/.claude/agents/`, or `.claude/agents/`). If none exist the wizard skips expert registration; you can re-run `/lazy-core.install` after adding agents.

## The journey

### Step 1 — Run `/lazy-core.install` inside the repo

Open a Claude Code session rooted in the target repository and run:

```
/lazy-core.install
```

The skill detects install scope automatically. Because the runtime is project-scoped, run it inside the repo rather than from a global session.

The install first verifies Python 3.12 or later is available. If Python is absent or too old, the skill surfaces the install options (Homebrew on macOS, pyenv cross-platform) and aborts; re-run once the floor is met.

### Step 2 — Answer yes to the runtime-daemon wizard

During install, the wizard asks whether to bootstrap runtime and experts for the repo. Answer **Yes**. The skill writes:

- `lazy.settings.json[experts]` — the experts section, initially containing only `_version`.
- `.claude/bin/lazy.runtime.sh` — the runtime shim, made executable. The shim resolves the latest `lazycortex-core/bin/runner` from the plugin cache at exec time, so it stays current after `/plugin update` without needing a re-run.
- `lazy-core.runtime` block inside `.claude/lazy.settings.json` — daemon configuration including polling interval (default: 5 seconds) and job-cleanup retention windows.
- `.memory/` directory at the repo root, unignored in `.gitignore` — tracked in git so memory notes survive clones.
- Entries in `.gitignore` covering `.experts/.jobs/` and `.logs/lazy-core/runtime/`.

Next, the wizard asks whether to scan for expert candidates and register them. Answer **Yes** and work through the per-candidate prompts (local name, git author name, git author email). When at least one expert is registered, the `lazy-expert.pump` routine is added to `routines` automatically. Because the pump routine was freshly added, the wizard then offers a daemon supervisor — choose **macOS launchd** or **Linux systemd** to start the daemon automatically on login, or **Skip** to start it by hand. On re-runs where the pump routine is already present, the supervisor offer does not appear; use your OS's service manager directly if you need to re-install the supervisor.

### Step 3 — Start the daemon

If you chose a supervisor in Step 2, the daemon is already running. If you skipped or want to start it manually, run from the repo root:

```
.claude/bin/lazy.runtime.sh
```

The daemon reads `lazy.settings.json[lazy-core.runtime]`, runs the `lazy-expert.pump` routine on each polling iteration, drains any `READY` jobs it finds, and loops. One daemon per repo means no two routines ever contend over the working tree or git state.

### Step 4 — Verify the daemon is polling (verification gate)

After one polling interval, open `.logs/lazy-core/runtime/state.json` and confirm the `last_run` timestamp is recent. If the timestamp is absent or stale, check that the shim is executable (`ls -l .claude/bin/lazy.runtime.sh`) and that Python 3.12+ is on your `$PATH`.

### Step 5 — Recover if the daemon halts

The daemon halts in two situations and writes a `daemon_halted` block to `.logs/lazy-core/runtime/state.json` in both cases. If you notice jobs stop processing, run:

```
/lazy-runtime.recover
```

The skill reads the halt context and shows you `triggered_by` (which routine or `lazy-expert.pump` caused the halt), `expert` + `job_id` (when the halt came from inside an expert job), and `reason` (the halt family).

**Working-tree halt (`uncommitted_changes`)** — a routine or expert left uncommitted changes behind. The skill also shows `dirty_paths` (the captured `git status --porcelain` output) and asks how to clean up before resuming:

- **commit** — stages everything and commits with a message you provide. Use when the dirty changes are intentional work you want to keep.
- **stash** — runs `git stash push -u`. Tucks the dirt away so you can restore it manually later.
- **discard** — runs `git checkout -- . && git clean -fd`. Throws away every dirty change. This is irreversible.
- **abort** — leaves everything as-is and exits. The daemon stays halted until you clean up manually and re-run the skill.

**Remote-sync halts (`git_pull_diverged` / `git_push_failed` / `git_remote_unavailable`)** — the daemon's pre- or post-tick remote sync hit an unrecoverable state. The skill does not attempt to fix these automatically (automatic resolution could silently drop your commits). Instead it surfaces reason-specific guidance — for example, inspecting `git log --oneline HEAD origin/<branch>` for a diverged branch, or checking network and `git remote -v` for a remote-unavailable halt. After you resolve the situation by hand, confirm **resume** to clear the halt block. The daemon's next tick re-evaluates; if the condition persists it will halt again with the same reason.

Once cleanup or manual repair succeeds and the tree is clean, the skill atomically clears the `daemon_halted` block from `state.json`. The daemon resumes scheduling on its next iteration with no restart required.

If the tree is still dirty after cleanup (e.g., a submodule left additional changes), the skill reports `still-dirty` and leaves the halt block in place. Run `git status` to inspect, resolve the remaining changes, and re-run `/lazy-runtime.recover`.

## After you're done

The daemon runs continuously, draining jobs and firing registered routines. The built-in `lazy-expert.pump` routine processes them serially per expert so there is never contention.

If you add new expert agents later, re-run `/lazy-core.install` — the wizard's expert-add phase picks up newly discovered agent files without touching existing registrations (it is idempotent). Because the pump routine is already registered on re-runs, the supervisor install offer will not appear again; only the first run that freshly registers the pump triggers it.

If a plugin needs its own periodic routine, run `/lazy-routine.register` to add it to the daemon's rotation.

After cloning the repo to a new machine, re-run `/lazy-core.install` — the shim, settings files, and `.memory/` directory are committed to the repo, but the daemon supervisor unit (launchd plist or systemd service) is per-user and is not in the repo. The wizard regenerates and loads it for the current machine.

The `daemon_halted` recovery path is an expected operational event, not an error in the daemon itself. When it fires often from a particular routine, that routine's output logic is leaving dirt behind — investigate there, not in the daemon.

## Adding periodic memory reflection

If you have persona-marked experts (see the `memory` block), you can register a periodic reflect routine so the daemon consolidates each expert's memory weekly:

Run `/lazy-routine.register` with:
- name: `lazy-memory.reflect-all`
- type: `subprocess`
- command: `["lazycortex-core", "memory-reflect-all"]`
- interval_sec: `604800` (7 days)

The routine dispatches one `kind=reflect` job per persona-marked expert on each fire. Experts that have not written memory yet get a no-op reflect (returns `outcome=empty`).

## How setup and recovery connect

```mermaid
%%{init: {'themeVariables':{'background':'transparent','primaryColor':'#1e3a5f','primaryBorderColor':'#4a90e2','primaryTextColor':'#fff','lineColor':'#4ae290','actorBkg':'#1e3a5f','actorBorder':'#4a90e2','actorTextColor':'#fff','actorLineColor':'#4a90e2','signalColor':'#4ae290','signalTextColor':'#000','noteBkgColor':'#5f4a1e','noteBorderColor':'#e2a14a','noteTextColor':'#fff','labelBoxBkgColor':'#5f4a1e','labelBoxBorderColor':'#e2a14a','labelTextColor':'#fff','loopTextColor':'#e2a14a'},'sequence':{'diagramPadding':5,'useMaxWidth':true}}}%%
sequenceDiagram
  participant user as User
  participant installSkill as /lazy-core.install wizard
  participant fsConfig as .claude/ config files
  participant daemon as lazy.runtime.sh daemon
  participant jobsDir as .experts/.jobs/
  participant stateFile as state.json
  participant recoverSkill as /lazy-runtime.recover

  Note over user,fsConfig: Phase 1 — Install and runtime opt-in
  user->>installSkill: run /lazy-core.install
  installSkill->>user: prompt — enable expert runtime?
  user-->>installSkill: opt in
  installSkill->>fsConfig: write .claude/bin/lazy.runtime.sh
  installSkill->>fsConfig: write lazy.settings.json [experts] block
  installSkill->>fsConfig: write lazy-core.runtime config block
  fsConfig-->>installSkill: files written
  installSkill-->>user: install complete

  Note over user,jobsDir: Phase 2 — Daemon start and poll loop
  user->>daemon: execute .claude/bin/lazy.runtime.sh
  daemon->>stateFile: write state running
  loop poll interval
    daemon->>jobsDir: scan .experts/.jobs/ for pending jobs
    jobsDir-->>daemon: job queue snapshot
  end

  Note over user,recoverSkill: Phase 3 — Dirty tree halt and recovery
  daemon->>stateFile: detect dirty working tree
  daemon->>stateFile: write daemon_halted to state.json
  user->>recoverSkill: run /lazy-runtime.recover
  recoverSkill->>stateFile: read halt context from state.json
  recoverSkill-->>user: show halt context and cleanup options
  alt commit
    user-->>recoverSkill: pick commit
    recoverSkill->>fsConfig: stage and commit dirty changes
  else stash
    user-->>recoverSkill: pick stash
    recoverSkill->>fsConfig: git stash dirty changes
  else discard
    user-->>recoverSkill: pick discard
    recoverSkill->>fsConfig: git checkout to discard changes
  end
  recoverSkill->>stateFile: clear daemon_halted flag
  stateFile-->>daemon: flag cleared on next iteration
  daemon->>jobsDir: resume polling .experts/.jobs/
```
