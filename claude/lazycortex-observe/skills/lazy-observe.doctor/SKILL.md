---
name: lazy-observe.doctor
description: "Read-only health check for the lazycortex-observe shipper on this host. Verifies service status, agent process, local /metrics endpoint, agent's own remote_write success counter, observer URL reachability, and WAL bounds. Reports each as PASS / WARN / FAIL with a one-line fix suggestion. Never mutates filesystem or service state."
allowed-tools: Read, Glob, Bash(launchctl *), Bash(systemctl *), Bash(curl *), Bash(test *), Bash(date *), Bash(ps *), Bash(du *), Bash(uname *), Bash(python3 *)
---
# Doctor lazy-observe

Confirm the metrics shipping pipeline is healthy end-to-end. The skill is intentionally read-only — it returns findings and suggested fixes, but never restarts services, never edits configs, never wipes WAL directories. Mutating fixes are the operator's call.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Read answer file`
   - `Step 2 — Service unit loaded`
   - `Step 3 — Agent process up`
   - `Step 4 — Local /metrics reachable`
   - `Step 5 — Agent self-metrics show successful remote_write`
   - `Step 6 — Observer URL reachable`
   - `Step 7 — WAL directory bounds`
   - `Step 8 — Report`
2. **Mark each task `in_progress` on enter and `completed` on exit.** Each step ends with one of `PASS` / `WARN` / `FAIL`.
3. **Do not reach the Report step until `TaskList` shows every prior task `completed`.**
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above with the severity word.

## Step 1 — Read answer file

Call `claude/lazycortex-observe/bin/install.read_answer_file()`. If the file is absent, report `FAIL not-installed` and skip the rest of the steps with outcome `n/a`.

Outcome: `PASS` (with the relevant fields echoed) / `FAIL not-installed`.

## Step 2 — Service unit loaded

- **darwin**: `launchctl print gui/$UID/com.lazycortex.observe`. Check `state = running` (or equivalent) in the output.
- **linux**: `systemctl --user is-active lazycortex-observe.service`. Expect `active`.

Outcome: `PASS active` / `FAIL inactive` / `WARN unknown`.

## Step 3 — Agent process up

`ps -o pid,comm -p <PID>` after extracting PID from the unit's status. Verify the binary path matches what the answer file declared.

Outcome: `PASS <pid>` / `FAIL no-pid`.

## Step 4 — Local /metrics reachable

`curl -fsS http://<scrape_target>/metrics`. Body must contain at least one `lazycortex_runtime_*` series. Sample one tick metric (`lazycortex_runtime_routine_ticks_total`) and report its current value.

Outcome: `PASS <sample value>` / `FAIL endpoint-down` / `FAIL no-lazycortex-series`.

## Step 5 — Agent self-metrics show successful remote_write

- **Alloy**: scrape `http://127.0.0.1:12345/metrics` (or whatever the operator configured). Check `prometheus_remote_storage_succeeded_samples_total` rate over the last minute > 0.
- **otelcol**: scrape `http://127.0.0.1:8888/metrics`. Check `otelcol_exporter_sent_metric_points` rate > 0.

Outcome: `PASS rate=<n>/min` / `WARN zero-rate` / `FAIL self-metrics-down`.

## Step 6 — Observer URL reachable

`curl -I --max-time 30 <remote_write_url>`. Any 2xx / 3xx / 401 / 405 → reachable (auth handshake reaches the right host). Network error → unreachable.

A 401 here is fine — it means the URL resolves but our request has no auth header (HEAD has no body to sign), which is a healthy signal that the host is up.

Outcome: `PASS reachable` / `FAIL unreachable`.

## Step 7 — WAL directory bounds

`du -sh <wal_dir>`. If the directory is over 10× `wal_max_age` worth of normal traffic (operator's call — print the size and let them judge), warn. If absent, the agent hasn't written any WAL yet — report `INFO empty`.

Outcome: `PASS <size>` / `WARN oversized` / `INFO empty`.

## Step 8 — Report

Render a markdown report. One line per Step 1–7 with `[SEVERITY] <step name> | <details>` and the suggested fix. The fix lines come from the per-step failure modes below — never invent new fixes.

Outcome: `reported`.

## Logging

Per the project's `lazy-log.logging` rule, log this run to `./.logs/claude/lazy-observe.doctor/<UTC timestamp>.md`.

## Failure modes (with suggested fixes)

- **FAIL not-installed** → run `/lazy-observe.install`.
- **FAIL inactive (Step 2)** → `launchctl kickstart -k gui/$UID com.lazycortex.observe` (darwin) or `systemctl --user restart lazycortex-observe.service` (linux). Check journal/Console for crash reason first.
- **FAIL no-pid (Step 3)** → service unit thinks it's running but the process exited; check the agent's stderr in `~/Library/Logs/lazycortex-observe/` (darwin) or via `journalctl --user -u lazycortex-observe.service` (linux).
- **FAIL endpoint-down (Step 4)** → lazycortex-core daemon is down OR `metrics.enabled: false`. Check `references/lazy-core.runtime-schema.md § 12`.
- **FAIL no-lazycortex-series (Step 4)** → endpoint is up but serving no samples; daemon hasn't dispatched a routine yet → wait for the first tick and re-run doctor.
- **WARN zero-rate (Step 5)** → agent is up but not delivering. Common causes: token expired (`/lazy-observe.install` Step 5), observer unreachable (Step 6 will catch), agent's WAL still recovering from outage.
- **FAIL self-metrics-down (Step 5)** → agent is up but its self-metrics endpoint isn't bound; usually a config typo. Re-render via `/lazy-observe.install` (writes are idempotent).
- **FAIL unreachable (Step 6)** → wrong URL, observer down, or DNS / firewall issue. The fix is on the operator's network, not in this plugin.
- **WARN oversized (Step 7)** → observer was offline long enough to accumulate WAL beyond expected bounds; once observer is back the WAL drains automatically. Truncating manually drops samples.
