---
name: lazy-core.daemon-authoring
description: "Use when a new daemon, cron job, or periodic process that calls an LLM is being written in any repository — before the first line of its launch command exists. Walks the routine-vs-standalone decision, wires every LLM call through the rate-limit-guarded `lazy-claude` wrapper, and hands over a launchd skeleton for the standalone case."
allowed-tools: Read, Glob, Grep, Bash, Write, Edit, AskUserQuestion, Agent
---
# Daemon Authoring

Guides the authoring of a new periodic process that spends LLM tokens, so it is born with the host's subscription rate-limit guard instead of being migrated onto it later. Prerequisite: `lazy-core.install` has run on this host at least once, so `~/.local/bin/lazy-claude` exists.

## Execution discipline (MANDATORY — read before any action)

This skill has 5 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Routine or standalone daemon`
   - `Step 2 — Wire LLM calls through lazy-claude`
   - `Step 3 — Supervisor skeleton`
   - `Step 4 — Report`
   - `Step 5 — Log the run`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it". No-ops count only if they emit an explicit outcome (`asserted`, `unchanged`, `skipped-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or explicitly `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Routine or standalone daemon

First question, always: does this need to be a separate daemon at all?

Check whether the target repository is driven by the lazycortex runtime — `.claude/lazy.settings.json` with a `routines` section, or a `com.lazycortex.runtime.*` supervisor unit for the checkout. If it is, the answer is a **routine**: register the periodic work via `/lazy-routine.register` (type `subprocess`, `schedule`, `git`, `inbox`, or `md-scan`) and let the existing daemon drive it — it already carries the rate-limit guard, serial scheduling, git discipline, and the error ledger. Do not write a second daemon next to a running one.

If the repository is not under the lazycortex runtime (or the process must outlive/precede it), proceed as a **standalone daemon**.

Confirm the choice via `AskUserQuestion` when the situation is ambiguous — an existing runtime but a workload that arguably needs its own lifecycle.

Outcome: `routine` (registered or handed to `/lazy-routine.register`) or `standalone`.

## Step 2 — Wire LLM calls through lazy-claude

Skip when Step 1 ended `routine` (outcome `skipped-routine-path`).

Every LLM invocation the daemon makes MUST go through the wrapper, by absolute path:

```
~/.local/bin/lazy-claude
```

- **Absolute path, never the bare word** — launchd and cron hand the process their own minimal `PATH`; a bare `lazy-claude` resolves to nothing there.
- **`exit 75` is not an error.** It means the host's subscription rate-limit window is closed and the call was refused before any tokens burned. The daemon treats it as a quiet skip: end the tick, try again on the next schedule, log at most one info line. Retrying in a loop or alerting on 75 defeats the guard.
- **`exit 69`** means no real `claude` executable was found on PATH — that IS an error worth surfacing.
- **Prefer `--output-format stream-json --verbose` for headless calls.** A streaming caller does not only read the shared flag — it replenishes it from the rate-limit frames of its own runs, so every other daemon on the host learns the window state sooner. A plain-text `-p` call gets the pre-call protection but contributes nothing back.
- Interactive use is unaffected: without `-p`/`--print` the wrapper replaces itself with the real `claude` untouched.
- Turning the guard off for one daemon = putting the bare word `claude` back in its launch command. The wrapper itself has no configuration.

Outcome: `wired` or `skipped-routine-path`.

## Step 3 — Supervisor skeleton

Skip when Step 1 ended `routine` (outcome `skipped-routine-path`).

For a macOS standalone daemon, start the plist from this skeleton (adjust label, interval, paths):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.<owner>.<name></string>
  <key>ProgramArguments</key><array>
    <string>/bin/sh</string><string>-c</string>
    <string>exec "$HOME/repos/<repo>/bin/<daemon>.sh"</string>
  </array>
  <key>StartInterval</key><integer>900</integer>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>StandardOutPath</key><string>/tmp/<name>.out.log</string>
  <key>StandardErrorPath</key><string>/tmp/<name>.err.log</string>
</dict></plist>
```

Rules the skeleton encodes:

- **Own `PATH`** — set it explicitly; the wrapper is still called by absolute path on top of that, but the real `claude` and any tools the daemon shells out to must be reachable.
- **`StartInterval` over `KeepAlive`** for periodic work — a tick process that exits beats a long-lived loop; use `KeepAlive` only for a process that genuinely must stay resident.
- **Logs to fixed files** — launchd captures stdout/stderr only when told where; without these keys failures are invisible.
- **State** lives in the daemon's own repo or under `${XDG_CACHE_HOME:-$HOME/.cache}/<name>/` — never in the plist directory, never in `/tmp` (wiped on reboot).

Linux equivalent: a systemd user timer + service pair with the same properties (explicit `Environment=PATH=…`, journal logging, `ExecStart` by absolute path).

Outcome: `skeleton-delivered` or `skipped-routine-path`.

## Step 4 — Report

One line per task in the canonical list, with its outcome word. A missing line is a bug.

## Step 5 — Log the run

Per the `lazy-log.logging` contract: `Bash(mkdir -p ./.logs/claude/lazy-core.daemon-authoring)`, then `Write` `./.logs/claude/lazy-core.daemon-authoring/<UTC-timestamp>.md` with frontmatter `git_sha`, `git_branch`, `date`, `input` and an Actions/Result body.

Outcome: `logged`.

## Failure modes

- **Every headless call of the new daemon exits 75 immediately** — the host's rate-limit flag is raised (a live record under `${XDG_CACHE_HOME:-$HOME/.cache}/lazycortex/rate-limit/`); the daemon is healthy, the subscription window is closed → wait for the window, or inspect the records to see who raised the flag and until when.
- **The daemon exits 69 under launchd but works in a shell** — the plist's `PATH` does not reach the real `claude` binary → add its directory to the `EnvironmentVariables` `PATH` key.
- **`~/.local/bin/lazy-claude` is missing** — `lazy-core.install` has not run on this host since the wrapper shipped → run `/lazy-core.install` (any repo) and re-check.
