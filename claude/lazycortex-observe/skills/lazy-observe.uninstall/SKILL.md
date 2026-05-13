---
name: lazy-observe.uninstall
description: "Tear down the lazycortex-observe shipper on this host: unload the launchd agent or systemd user unit, remove rendered configs and the WAL dir. Operator-private state under `${XDG_CONFIG_HOME:-~/.config}/lazycortex/` is preserved by default — re-installing later picks it up. Idempotent — re-running on an already-clean host is a no-op."
allowed-tools: Read, Glob, Bash(rm *), Bash(launchctl *), Bash(systemctl *), Bash(test *), Bash(date *), Bash(uname *), Bash(python3 *)
---
# Uninstall lazy-observe

Symmetric undo for `/lazy-observe.install`. Removes the running service and the rendered configs. Leaves operator-private answers (URL, auth choice) intact unless the operator opts in to wiping them.

## Execution discipline (MANDATORY — read before any action)

This skill has 6 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Detect host`
   - `Step 2 — Unload service`
   - `Step 3 — Remove rendered configs`
   - `Step 4 — Remove WAL + log directories`
   - `Step 5 — Offer to wipe answer file + token`
   - `Step 6 — Report`
2. **Mark each task `in_progress` on enter and `completed` on exit.** No-ops count only with an explicit outcome word (`removed`, `absent`, `kept-per-user-choice`, …).
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or `skipped` with an outcome.**
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above.

## Step 1 — Detect host

Same logic as `/lazy-observe.install` Step 1. Map `darwin` → launchd, `linux` → systemd user.

Outcome: `darwin` / `linux` / `unsupported-platform`.

## Step 2 — Unload service

- **darwin**: call `claude/lazycortex-observe/bin/install.unload_service_macos(<plist_path>)`. Plist path is `~/Library/LaunchAgents/com.lazycortex.observe.plist`.
- **linux**: call `install.unload_service_linux()`.

Both helpers tolerate "not loaded" exit codes and return a (`ok`, `stderr`) tuple. Treat "not loaded" as `absent`, not as an error.

Outcome: `unloaded` / `absent`.

## Step 3 — Remove rendered configs

Delete (if present):
- `${XDG_DATA_HOME:-~/.local/share}/lazycortex/observe/agent.river`
- `${XDG_DATA_HOME:-~/.local/share}/lazycortex/observe/agent.yaml`
- `~/Library/LaunchAgents/com.lazycortex.observe.plist` (darwin only)
- `~/.config/systemd/user/lazycortex-observe.service` (linux only)

Outcome: `removed` (with file count) / `absent`.

## Step 4 — Remove WAL + log directories

Ask via `AskUserQuestion`: keep or delete the WAL directory at `${XDG_DATA_HOME:-~/.local/share}/lazycortex/observe/wal/`? Default `keep` — WAL preserves not-yet-shipped samples, and reinstalling the same agent will pick them up.

Same for log directory (`~/Library/Logs/lazycortex-observe/` on darwin, `${XDG_STATE_HOME:-~/.local/state}/lazycortex/observe/logs/` on linux).

Outcome: `removed` / `kept-per-user-choice` / `absent`.

## Step 5 — Offer to wipe answer file + token

`AskUserQuestion` — keep or delete the operator-private state at `${XDG_CONFIG_HOME:-~/.config}/lazycortex/observe.toml` and `${XDG_CONFIG_HOME:-~/.config}/lazycortex/observe.token`? Default `keep` — these are the only place URL/auth choices live, and a future install picks them up automatically.

If the operator chooses to delete the token file, do it via `rm -f` (the file may already be 0600).

Outcome: `kept-per-user-choice` / `wiped`.

## Step 6 — Report

Render a markdown report. One line per Step 1–5 with its outcome word.

Outcome: `reported`.

## Logging

Per the project's `lazy-log.logging` rule, log this run to `./.logs/claude/lazy-observe.uninstall/<UTC timestamp>.md`.

## Failure modes

- **`launchctl bootout` returns 5 ("Input/output error")** — symptom: bootout fails on macOS after a system update → cause: stale plist label registration → fix: `launchctl remove com.lazycortex.observe`, then rerun.
- **`systemctl --user disable` returns "Unit lazycortex-observe.service does not exist"** — symptom: unit file already gone → cause: prior partial uninstall → fix: `systemctl --user daemon-reload`, then rerun. The skill treats this as `absent`, not an error.
