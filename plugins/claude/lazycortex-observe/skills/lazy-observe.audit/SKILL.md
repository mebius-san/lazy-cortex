---
name: lazy-observe.audit
description: "Run when metrics stopped reaching the observer, a dashboard went flat, an alert says the shipper is down, or the operator asks whether metrics shipping is healthy on this host. Delegated from `lazy-core.doctor` Phase 3. Read-only end-to-end check of the service unit, agent process, local `/metrics` endpoints, remote_write success, observer reachability, and WAL size — it reports findings with PASS / INFO / WARN / FAIL, each carrying its own repair route, and never applies them."
allowed-tools: Read, Glob, Bash(launchctl *), Bash(systemctl *), Bash(curl *), Bash(test *), Bash(date *), Bash(ps *), Bash(du *), Bash(uname *), Bash(python3 *), Bash("${LAZYCORTEX_PYTHON:-python3}" *), Bash(mkdir -p *), Bash(git rev-parse*), Write, Agent
---
# Audit lazy-observe

Confirm the metrics shipping pipeline is healthy end-to-end. The skill is intentionally read-only — it returns findings, but never restarts services, never edits configs, never wipes WAL directories. Mutating fixes are the operator's call. It writes nothing at all — its report is its return value.

The run follows the shared audit shape in `plugins/claude/lazycortex-core/references/lazy-core.audit-contract.md` — severity vocabulary, finding shape, and the read-only boundary come from there.

## Execution discipline (MANDATORY — read before any action)

This skill has 8 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, write out the step ledger — one line per step below, each marked `pending` — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Read answer file`
   - `Step 2 — Service unit loaded`
   - `Step 3 — Agent process up`
   - `Step 4 — Local /metrics reachable`
   - `Step 5 — Agent self-metrics show successful remote_write`
   - `Step 6 — Observer URL reachable`
   - `Step 7 — WAL directory bounds`
   - `Step 9 — Report`
2. **Re-emit the ledger line for each step — `in_progress` on enter, `completed` on exit.** Each check step ends with one of `PASS` / `INFO` / `WARN` / `FAIL`.
3. **Do not reach the Report step until the ledger shows every prior task `completed`.**
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above with the severity word and that step's repair route.

## Step 1 — Read answer file

Run `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/install.py" read-answers)` — it prints the answer file as JSON, `{}` when absent. If the file is absent, the verdict comes from the fact of collection, not from the file: run `Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/install.py" detect-coverage)` first.

- Coverage verdict `already-covered` → collection works on this host but observe has no record of it — report `WARN covered-unconfigured` (echo the detected signals) and skip the rest of the steps with outcome `n/a`. The fix is `/lazy-observe.install`, which records integrate mode automatically.
- Coverage verdict `clear` → report `FAIL not-installed` and skip the rest of the steps with outcome `n/a`.

Outcomes:

- `PASS` — the answer file reads; echo the relevant fields.
- `WARN covered-unconfigured` — a collector already scrapes this host but `observe.toml` is absent → run `/lazy-observe.install`; it detects the coverage and records integrate mode without questions.
- `FAIL not-installed` — nothing collects this host's metrics and no shipper is configured → run `/lazy-observe.install`.

## Step 2 — Service unit loaded

In integrate mode (`mode = "integrate"` in the answer file) no shipper unit is expected — state `n/a integrate-mode` and continue.

- **darwin**: `launchctl print gui/$UID/com.lazycortex.observe`. Check `state = running` (or equivalent) in the output.
- **linux**: `systemctl --user is-active lazycortex-observe.service`. Expect `active`.

Outcomes:

- `PASS active` — the unit is loaded and running.
- `WARN unknown` — the unit's state did not parse → read the unit's own status output on this host before judging.
- `FAIL inactive` — the unit is loaded but not running → check the journal (linux) or Console (darwin) for the crash reason first, then `launchctl kickstart -k gui/$UID com.lazycortex.observe` (darwin) or `systemctl --user restart lazycortex-observe.service` (linux).
- `n/a integrate-mode` — no shipper unit is expected in integrate mode.

## Step 3 — Agent process up

In integrate mode — `n/a integrate-mode`, continue.

`ps -o pid,comm -p <PID>` after extracting PID from the unit's status. Verify the binary path matches what the answer file declared.

Outcomes:

- `PASS <pid>` — the process runs from the binary the answer file declared.
- `FAIL no-pid` — the service unit thinks it is running but the process exited → read the agent's stderr in `~/Library/Logs/lazycortex-observe/` (darwin) or via `journalctl --user -u lazycortex-observe.service` (linux).
- `n/a integrate-mode` — no local agent process in integrate mode.

## Step 4 — Local /metrics reachable (every daemon)

List the host's metrics-enabled daemons and probe each endpoint:

```
Bash("${LAZYCORTEX_PYTHON:-python3}" "${CLAUDE_PLUGIN_ROOT}/bin/install.py" smoke)
```

One report line per daemon (`<repo_label> <addr> True/False`), then a trailing `none-registered` or `done` line this audit ignores. Every body must contain at least one `lazycortex_runtime_*` series; sample `lazycortex_runtime_routine_ticks_total` where reachable.

Outcomes:

- `PASS <N>-of-<M>` — every registered daemon answered with `lazycortex_runtime_*` series.
- `FAIL endpoint-down (<repo_label> ...)` — that repo's lazycortex-core daemon is down, or its `metrics.enabled` is `false` → see `plugins/claude/lazycortex-core/references/lazy-core.metrics-schema.md` for the settings the daemon reads.
- `FAIL no-lazycortex-series (<repo_label>)` — the endpoint is up but serves no samples; the daemon has not dispatched a routine yet → wait for the first tick and re-run `/lazy-observe.audit`.
- `FAIL no-daemons-registered` — no repo on this host has a metrics-enabled daemon → see `plugins/claude/lazycortex-core/references/lazy-core.metrics-schema.md` for the settings that register one.

## Step 5 — Agent self-metrics show successful remote_write

In integrate mode (`mode = "integrate"` in the answer file) there is no local shipper — instead verify the scrape-targets file exists at `${XDG_CONFIG_HOME:-~/.config}/lazycortex/scrape-targets.json`, parses as JSON, and its entry count matches Step 4's daemon count.

Outcomes in integrate mode:

- `PASS file-sd <count> targets` — the file parses and its entry count matches Step 4's daemon count.
- `WARN scrape-file-stale` — the file's entry count disagrees with Step 4 → run `/lazy-observe.install --integrate-only`, which regenerates it.
- `FAIL scrape-file-missing` — no scrape-targets file at that path, so the operator's Prometheus has nothing to scrape → run `/lazy-observe.install --integrate-only`.

Otherwise (standalone shipper):

- **Alloy**: scrape `http://127.0.0.1:12345/metrics` (or whatever the operator configured). Check `prometheus_remote_storage_succeeded_samples_total` rate over the last minute > 0.
- **otelcol**: scrape `http://127.0.0.1:8888/metrics`. Check `otelcol_exporter_sent_metric_points` rate > 0.

Outcomes for a standalone shipper:

- `PASS rate=<n>/min` — samples are leaving the host.
- `WARN zero-rate` — the agent is up but delivering nothing; the usual causes are an expired token (re-run `/lazy-observe.install` and answer its token step), an unreachable observer (Step 6 catches that one), or a WAL still draining after an outage.
- `FAIL self-metrics-down` — the agent's self-metrics endpoint is not bound, usually a config typo → re-render the config via `/lazy-observe.install` (its writes are idempotent).

## Step 6 — Observer URL reachable

`curl -I --max-time 30 <remote_write_url>`. Any 2xx / 3xx / 401 / 405 → reachable (auth handshake reaches the right host). Network error → unreachable.

A 401 here is fine — it means the URL resolves but our request has no auth header (HEAD has no body to sign), which is a healthy signal that the host is up.

Outcomes:

- `PASS reachable` — the observer host answers.
- `FAIL unreachable` — wrong URL, observer down, or a DNS / firewall issue → the route is the operator's own network and the `remote_write_url` in `observe.toml`, not a skill in this plugin.

## Step 7 — WAL directory bounds

`du -sh <wal_dir>`. If the directory is over 10× `wal_max_age` worth of normal traffic (operator's call — print the size and let them judge), warn. If absent, the agent hasn't written any WAL yet — report `INFO empty`.

Outcomes:

- `PASS <size>` — the WAL is within the bounds the operator judged.
- `INFO empty` — the agent has written no WAL yet; nothing to act on.
- `WARN oversized` — the observer was offline long enough to accumulate WAL beyond expected bounds → leave it alone and fix the observer (Step 6's route); the WAL drains itself once the observer is back, and truncating it by hand drops samples.

## Step 9 — Report

Render a markdown report. One line per Step 1–7 in the contract's finding shape:

```
[<SEVERITY>] <step name> — <what is wrong>; <repair route>
```

The route on each line is the one that step's own outcome list names, never a new one, and never lifted into a trailing recommendations section. Close with the contract's summary line — `audit: <PASS|WARN|FAIL> (<n> findings)`, the verdict being the highest severity present and `INFO` counting as `PASS`.

Outcome: `reported`.
