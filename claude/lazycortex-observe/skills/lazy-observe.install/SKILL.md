---
name: lazy-observe.install
description: "Bootstrap the lazycortex-observe shipper for this host: pick agent kind (Alloy / otelcol), collect remote_write URL + auth, render the agent config + service unit from shipped templates, install + load the supervised service, smoke-test the local /metrics endpoint. Genuine config (URL, auth, agent kind) is read-first from `${XDG_CONFIG_HOME:-~/.config}/lazycortex/` and never re-asked once on record; rendered files follow the silent file-sync policy. Idempotent and quiet on re-run — re-running rewrites the rendered configs and reloads the service without prompting."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(chmod *), Bash(launchctl *), Bash(systemctl *), Bash(test *), Bash(date *), Bash(brew *), Bash(which *), Bash(curl *), Bash(uname *), Bash(python3 *)
---
# Install lazy-observe

Bring up a Prometheus-format metrics shipper on the current host that scrapes the lazycortex-core daemon's `/metrics` endpoint and forwards via `remote_write` to the operator's observer (self-hosted Prometheus / Mimir / etc.).

The plugin ships **observer-server-blind** templates only. This skill collects operator-private values (URL, token, basic-auth username, agent kind) at install time and persists them under `${XDG_CONFIG_HOME:-~/.config}/lazycortex/` — never in the plugin tree, never in tracked settings. These are GENUINE config that cannot be derived; the questions stay, but they are **read-first** — a value already on record is reused silently and never re-asked.

## File-sync policy (applies to every file this skill renders)

Every file this skill renders or writes (agent config, service unit from shipped templates) follows three cases — no per-file "install?" prompt, no drift wizard:

1. **Absent or unchanged** — target missing, or byte-identical to the freshly-rendered version → write silently. State `rendered` / `unchanged`.
2. **Locally changed but cleanly mergeable** — target diverged, but re-rendering only overwrites the generated region while every operator-owned value is preserved (no contradiction) → render silently. State `rendered`.
3. **Genuine conflict** — the same region was changed both locally and in the freshly-rendered version in ways that cannot be reconciled automatically → the ONLY case that asks. `AskUserQuestion` naming the file, quoting the conflicting region, options `take-rendered` / `keep-local`.

"Conflict" means you cannot determine what should survive — not merely "the bytes differ". Re-rendering = overwrite the generated region, preserve operator-owned values; no contradiction → no question.

## Read-first config (never re-ask)

Genuine config (`agent_kind`, `remote_write_url`, `auth_kind`, `basic_auth_username`) lives under `${XDG_CONFIG_HOME:-~/.config}/lazycortex/observe.toml`. Before any config question, read that file: if the value is already on record, reuse it silently and SKIP the question (outcome `kept-existing`). Ask only when nothing is on record. Persist every collected answer back so the next run is silent.

## Execution discipline (MANDATORY — read before any action)

This skill has 11 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 1 — Detect host`
   - `Step 2 — Verify lazycortex-core metrics endpoint`
   - `Step 3 — Collect agent kind`
   - `Step 4 — Collect remote_write URL`
   - `Step 5 — Collect auth kind + credentials`
   - `Step 6 — Persist non-secret answers`
   - `Step 7 — Render agent config`
   - `Step 8 — Render + install service unit`
   - `Step 9 — Detect or guide install of agent binary`
   - `Step 10 — Load service + smoke test`
   - `Step 11 — Report`
2. **Mark each task `in_progress` on enter and `completed` on exit.** "Completed" means "I executed the step's logic AND produced an outcome word for it" (e.g. `installed`, `unchanged`, `skipped-per-user-choice`, `aborted`). No-ops count only with an explicit outcome.
3. **Do not reach the Report step until `TaskList` shows every prior task `completed` or `skipped` with an outcome.** A still-`pending` task is a bug — stop and execute it first.
4. **The Report step is a structural verifier.** Its output MUST contain one line per task above. A missing line is a bug; do not render the report with gaps.

## Step 1 — Detect host

Call `python3 -c "import sys; print(sys.platform)"`. Map:

- `darwin` → use launchd (`com.lazycortex.observe.plist.j2`).
- `linux` → use systemd user unit (`lazycortex-observe.service.j2`).
- anything else → abort with outcome `unsupported-platform`.

Outcome: `darwin` / `linux` / `unsupported-platform`.

## Step 2 — Verify lazycortex-core metrics endpoint

`curl -fsS http://127.0.0.1:9464/metrics > /dev/null` (or whichever port the operator configured). If it 404s, lazycortex-core isn't running with `metrics.enabled: true`. Tell the operator how to enable it (point at `references/lazy-core.runtime-schema.md § 12`) and abort with outcome `core-metrics-disabled`.

If the endpoint binds on a non-default port, ask via `AskUserQuestion` for the actual `host:port` and remember it as `scrape_target`.

Outcome: `reachable` / `core-metrics-disabled`.

## Step 3 — Collect agent kind

Read `${XDG_CONFIG_HOME:-~/.config}/lazycortex/observe.toml` first (per Read-first config). If `agent_kind` is already on record, reuse it silently and skip the question (outcome `kept-existing`).

Otherwise `AskUserQuestion` — single question, two options:

- **Grafana Alloy** (recommended for Grafana Cloud / Mimir-stack operators).
- **OpenTelemetry Collector** (vendor-neutral; recommended for everyone else).

Persist the choice as `agent_kind` ∈ `{alloy, otelcol}`.

Outcome: `alloy` / `otelcol` / `kept-existing`.

## Step 4 — Collect remote_write URL

Read `observe.toml` first. If `remote_write_url` is already on record, reuse it silently and skip the question (outcome `kept-existing`) — do NOT re-prompt to keep-or-overwrite.

Otherwise `AskUserQuestion` — single free-form prompt for the operator's Prometheus `remote_write` endpoint URL. Validate that it parses as `http(s)://...`. Persist as `remote_write_url`.

Outcome: `collected` / `kept-existing`.

## Step 5 — Collect auth kind + credentials

Read `observe.toml` first. If `auth_kind` (and `basic_auth_username` when applicable) is already on record, reuse it silently and skip both the kind and source questions (outcome `kept-existing`) — the operator's token continues to be sourced from the env var or 0600 file as previously recorded.

Otherwise `AskUserQuestion` — single question, three options:

- **Bearer token** — token sourced from `LAZYCORTEX_OBSERVE_TOKEN` env var or a 0600 file at `${XDG_CONFIG_HOME:-~/.config}/lazycortex/observe.token`.
- **Basic auth** — username collected here; password sourced same way as bearer.
- **None** — no auth (e.g. mTLS-fronted observer or in-VPC plain HTTP).

If bearer or basic, ask a follow-up `AskUserQuestion` for token-source: `env` (operator handles export themselves) or `file` (we write it 0600). On `file`, prompt for the token value once and call `claude/lazycortex-observe/bin/install.write_token_file()`. Never write the token into the answer file.

Outcome: `bearer-env` / `bearer-file` / `basic-env` / `basic-file` / `none` / `kept-existing`.

## Step 6 — Persist non-secret answers

Call `claude/lazycortex-observe/bin/install.write_answer_file()` with:

- `agent_kind`
- `remote_write_url`
- `auth_kind` ∈ `{bearer, basic, none}`
- `basic_auth_username` (only if auth_kind = basic)
- `scrape_target` (default `127.0.0.1:9464`)
- `scrape_interval` (default `15s`)
- `wal_max_age` (default `12h`)
- `host_kind` ∈ `{darwin, linux}`

The helper refuses to write any key named `token` or `LAZYCORTEX_OBSERVE_TOKEN` — defense-in-depth against accidental secret leakage.

Outcome: `persisted` (path: `${XDG_CONFIG_HOME:-~/.config}/lazycortex/observe.toml`).

## Step 7 — Render agent config

Call `install.render_to(<template>, vars, target)` where:

- `<template>` = `alloy.river.j2` if `agent_kind=alloy`, else `otelcol.yaml.j2`.
- `target` = `${XDG_DATA_HOME:-~/.local/share}/lazycortex/observe/agent.river` or `agent.yaml`.

Apply the File-sync policy to `target`: absent / unchanged → write silently; locally edited but the generated region overwrites cleanly with operator-owned values preserved → render silently; only a genuine conflict asks. No per-file "overwrite?" prompt.

Outcome: `rendered` / `unchanged`.

## Step 8 — Render + install service unit

Two paths by host:

- **darwin**: render `com.lazycortex.observe.plist.j2` → `~/Library/LaunchAgents/com.lazycortex.observe.plist`. Set vars: `agent_binary`, `agent_args`, `rendered_config_path` (from Step 7), `wal_dir`, `log_dir`, `home`, `token_source`, `token_file`.
- **linux**: render `lazycortex-observe.service.j2` → `~/.config/systemd/user/lazycortex-observe.service`. Set vars: `agent_binary`, `agent_args`, `rendered_config_path`, `wal_dir`, `log_dir`, `env_file`.

Apply the File-sync policy to the rendered unit file (per Step 7) — silent render on absent / unchanged / cleanly-overwritable, ask only on genuine conflict.

Outcome: `rendered` / `unchanged`.

## Step 9 — Detect or guide install of agent binary

Call `install.find_agent_binary(agent_kind)`. If missing:

- **darwin**: print `brew install grafana/grafana/alloy` (or `otelcol-contrib`) and abort with outcome `agent-binary-missing-instructions-printed`. Never run `brew install` automatically — operator decides.
- **linux**: print the distro-specific install instruction (Debian/Ubuntu: `apt install grafana-alloy` from Grafana's repo; Fedora: `dnf install ...`). Abort with same outcome.

If present, capture its absolute path and proceed.

Outcome: `present` / `agent-binary-missing-instructions-printed`.

## Step 10 — Load service + smoke test

- **darwin**: `install.load_service_macos(plist_path)`.
- **linux**: `install.load_service_linux()`.

Then poll for up to 30s: `install.smoke_test_local_metrics(scrape_target)` until the body contains `lazycortex_runtime`. If it never does, surface the agent binary's own self-metrics endpoint (Alloy: `http://127.0.0.1:12345/-/ready`; otelcol: `http://127.0.0.1:8888/metrics`) for the operator to debug.

Outcome: `up` / `loaded-but-not-up`.

## Step 11 — Report

Render a markdown report. Severity: `PASS` / `WARN` / `FAIL`. One line per Step 1–10 with its outcome word. Include the answer-file path, rendered-config path, service-unit path, and the smoke-test summary.

Outcome: `reported`.

## Logging

Per the project's `lazy-log.logging` rule, log this run to `./.logs/claude/lazy-observe.install/<UTC timestamp>.md`. Frontmatter: `git_sha`, `git_branch`, `date`, `input`. Body: `## Actions` (one bullet per Step) and `## Result` (PASS/WARN/FAIL summary). Use `Bash(mkdir -p ...)` then `Write` — never chain.

## Failure modes

- **Operator already has a different shipper running on the same launchctl label / unit name** — symptom: `bootstrap` / `enable` errors with "already loaded" → cause: previous install or operator-managed copy → fix: run `/lazy-observe.uninstall` first, then re-run install.
- **lazycortex-core daemon down** — symptom: Step 2 returns `core-metrics-disabled` even after enabling `metrics.enabled: true` → cause: daemon not started or not reloaded after settings flip → fix: restart the daemon supervisor (`launchctl kickstart -k gui/$UID com.lazycortex.runtime` or `systemctl --user restart lazycortex-runtime.service`).
- **remote_write 401/403 in agent self-metrics** — symptom: `prometheus_remote_storage_failed_samples_total` non-zero in agent's own scrape → cause: token wrong, expired, or missing scope → fix: rotate via `install.write_token_file(<new>)` and reload the service.
