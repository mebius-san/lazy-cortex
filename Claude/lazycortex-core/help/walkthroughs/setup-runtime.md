---
chapter_type: walkthrough
summary: Bootstrap the per-repo serial daemon so the async expert team has an executor — install wizard, start the daemon, then unblock it with /lazy-runtime.recover if the working tree halts.
last_regen: 2026-05-08
diagram_spec:
  anchor: "How setup and recovery connect"
  request: "Sequence diagram showing three phases: (1) User runs /lazy-core.install, wizard asks about runtime, user opts in, wizard writes .claude/bin/lazy.runtime.sh + experts.settings.json + lazy-core.runtime block; (2) User runs .claude/bin/lazy.runtime.sh (daemon starts, polls .experts/.jobs/ on interval); (3) Working tree goes dirty, daemon writes daemon_halted to .logs/lazy-core/runtime/state.json, user runs /lazy-runtime.recover, skill shows halt context, user picks cleanup mode (commit/stash/discard), skill clears daemon_halted, daemon resumes on next iteration."
  kind_hint: sequence
source_skills:
  - lazy-core.install
  - lazy-runtime.recover
---
# How do I bootstrap the runtime daemon and recover it if the working tree halts?

The expert runtime gives you a serial, per-repo daemon that drains a job queue and runs registered plugin routines — without hitting Claude Code's subagent nesting limit. Setting it up takes three actions: run the runtime-daemon wizard inside `/lazy-core.install`, start the daemon with `.claude/bin/lazy.runtime.sh`, and know how to unblock it with `/lazy-runtime.recover` if a job or routine leaves the working tree dirty.

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

### Step 2 — Answer yes to the runtime-daemon wizard

During install, the wizard asks whether to bootstrap runtime and experts for the repo. Answer **Yes**. The skill writes:

- `.experts/experts.settings.json` — registered expert entries.
- `.claude/bin/lazy.runtime.sh` — the runtime shim, made executable.
- `lazy-core.runtime` block inside `.claude/lazy.settings.json` — daemon configuration and the built-in polling interval (default: 5 seconds).
- Entries in `.gitignore` covering `.experts/.jobs/` and `.logs/lazy-core/runtime/`.

The shim resolves the latest `lazycortex-core/bin/runner` from the plugin cache at exec time, so it stays current after `/plugin update` without needing a re-run.

Next, the wizard asks whether to scan for expert candidates and register them. Answer **Yes** and work through the per-candidate prompts (local name, git author name, git author email). When at least one expert is registered, the `lazy-expert.pump` routine is added to `lazy-core.runtime.routines` automatically. Because the pump routine was freshly added, the wizard then offers a daemon supervisor — choose **macOS launchd** or **Linux systemd** to start the daemon automatically on login, or **Skip** to start it by hand. On re-runs where the pump routine is already present, the supervisor offer does not appear; use your OS's service manager directly if you need to re-install the supervisor.

### Step 3 — Start the daemon

If you chose a supervisor in Step 2, the daemon is already running. If you skipped or want to start it manually, run from the repo root:

```
.claude/bin/lazy.runtime.sh
```

The daemon reads `lazy.settings.json[lazy-core.runtime]`, runs the `lazy-expert.pump` routine on each polling iteration, drains any `READY` jobs it finds, and loops. One daemon per repo means no two routines ever contend over the working tree or git state.

To verify the daemon is alive, check `.logs/lazy-core/runtime/state.json` — a running daemon writes `last_run` on each iteration.

### Step 4 — Verify the daemon is polling (verification gate)

After one polling interval, open `.logs/lazy-core/runtime/state.json` and confirm the `last_run` timestamp is recent. If the timestamp is absent or stale, check that the shim is executable (`ls -l .claude/bin/lazy.runtime.sh`) and that Python 3.12+ is on your `$PATH`.

### Step 5 — Recover if the working tree halts

The daemon halts automatically when a routine or expert leaves the working tree dirty — it writes a `daemon_halted` block to `.logs/lazy-core/runtime/state.json` and stops scheduling. If you notice jobs stop processing, run:

```
/lazy-runtime.recover
```

The skill reads the halt context and surfaces:

- `triggered_by` — which routine or `lazy-expert.pump` caused the halt.
- `expert` + `job_id` — populated when the dirt came from inside an expert job.
- `dirty_paths` — the captured `git status --porcelain` lines.

It then asks how to clean up before resuming:

- **commit** — stages everything and commits with a message you provide. Use when the dirty changes are intentional work you want to keep.
- **stash** — runs `git stash push -u`. Tucks the dirt away so you can restore it manually later.
- **discard** — runs `git checkout -- . && git clean -fd`. Throws away every dirty change. This is irreversible.
- **abort** — leaves everything as-is and exits. The daemon stays halted until you clean up manually and re-run the skill.

Once cleanup succeeds and the tree is clean, the skill atomically clears the `daemon_halted` block from `state.json`. The daemon resumes scheduling on its next iteration with no restart required.

If the tree is still dirty after cleanup (e.g., a submodule left additional changes), the skill reports `still-dirty` and leaves the halt block in place. Run `git status` to inspect, resolve the remaining changes, and re-run `/lazy-runtime.recover`.

## After you're done

The daemon runs continuously, draining jobs and firing registered routines. The built-in `lazy-expert.pump` routine processes them serially per expert so there is never contention.

If you add new expert agents later, re-run `/lazy-core.install` — the wizard's expert-add phase picks up newly discovered agent files without touching existing registrations (it is idempotent). Because the pump routine is already registered on re-runs, the supervisor install offer will not appear again; only the first run that freshly registers the pump triggers it.

If a plugin needs its own periodic routine, run `/lazy-routine.register` to add it to the daemon's rotation.

After cloning the repo to a new machine, re-run `/lazy-core.install` — the shim and settings files are committed, but the daemon supervisor unit (launchd plist or systemd service) is per-user and is not in the repo. The wizard regenerates and loads it for the current machine.

The `daemon_halted` recovery path is an expected operational event, not an error in the daemon itself. When it fires often from a particular routine, that routine's output logic is leaving dirt behind — investigate there, not in the daemon.

## How setup and recovery connect

```mermaid
%%{init: {'themeVariables':{'background':'transparent','primaryColor':'#1e3a5f','primaryBorderColor':'#4a90e2','primaryTextColor':'#fff','lineColor':'#4ae290','actorBkg':'#1e3a5f','actorBorder':'#4a90e2','actorTextColor':'#fff','actorLineColor':'#4a90e2','signalColor':'#4ae290','signalTextColor':'#000','noteBkgColor':'#5f4a1e','noteBorderColor':'#e2a14a','noteTextColor':'#fff','labelBoxBkgColor':'#5f4a1e','labelBoxBorderColor':'#e2a14a','labelTextColor':'#fff','loopTextColor':'#e2a14a'},'sequence':{'diagramPadding':5,'useMaxWidth':true}}}%%
sequenceDiagram
  participant user as User
  participant installSkill as /lazy-core.install wizard
  participant fs as File System
  participant daemon as lazy.runtime.sh daemon
  participant jobsDir as .experts/.jobs/
  participant stateFile as .logs/lazy-core/runtime/state.json
  participant recoverSkill as /lazy-runtime.recover

  Note over user,fs: Phase 1 — Install

  user->>installSkill: run /lazy-core.install
  installSkill->>user: prompt - enable runtime daemon?
  user-->>installSkill: opt in
  installSkill->>fs: write .claude/bin/lazy.runtime.sh
  installSkill->>fs: write experts.settings.json
  installSkill->>fs: write lazy-core.runtime block in config
  fs-->>installSkill: files written
  installSkill-->>user: install complete - runtime enabled

  Note over user,jobsDir: Phase 2 — Daemon Start

  user->>daemon: execute .claude/bin/lazy.runtime.sh
  daemon->>stateFile: write state=running
  loop poll interval
    daemon->>jobsDir: scan .experts/.jobs/ for pending jobs
    jobsDir-->>daemon: job list (empty or queued)
  end

  Note over daemon,recoverSkill: Phase 3 — Dirty Tree and Recovery

  daemon->>fs: detect working tree dirty
  daemon->>stateFile: write daemon_halted + halt context
  Note over stateFile: state=daemon_halted
  daemon-->>user: daemon paused - tree is dirty

  user->>recoverSkill: run /lazy-runtime.recover
  recoverSkill->>stateFile: read daemon_halted context
  stateFile-->>recoverSkill: halt context payload
  recoverSkill-->>user: show halt context - pick cleanup mode
  alt commit
    user-->>recoverSkill: choose commit
    recoverSkill->>fs: stage and commit dirty changes
  else stash
    user-->>recoverSkill: choose stash
    recoverSkill->>fs: git stash dirty changes
  else discard
    user-->>recoverSkill: choose discard
    recoverSkill->>fs: git checkout -- discard changes
  end
  recoverSkill->>stateFile: clear daemon_halted - write state=running
  stateFile-->>recoverSkill: state cleared
  recoverSkill-->>user: recovery complete - daemon will resume
  daemon->>stateFile: read state on next iteration
  stateFile-->>daemon: state=running
  daemon->>jobsDir: resume polling .experts/.jobs/
```
