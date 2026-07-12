---
name: lazy-observe.install
description: "Bootstrap the lazycortex-observe shipper for this host: pre-flight-detect an already-working collection stack (and abort untouched when one exists), pick agent kind (Alloy / otelcol), collect remote_write URL + auth, render the agent config + service unit covering EVERY local runtime daemon, install + load the supervised service, smoke-test the local /metrics endpoints. Supports `--integrate-only` (contribute a Prometheus file_sd scrape-targets file to an existing stack, install no shipper) and `--force-standalone` (install the shipper despite detected coverage). Genuine config (URL, auth, agent kind) is read-first from `${XDG_CONFIG_HOME:-~/.config}/lazycortex/` and never re-asked once on record; rendered files follow the silent file-sync policy. Idempotent and quiet on re-run."
allowed-tools: Read, Write, Edit, Glob, Bash(mkdir -p *), Bash(chmod *), Bash(launchctl *), Bash(systemctl *), Bash(test *), Bash(date *), Bash(brew *), Bash(which *), Bash(curl *), Bash(uname *), Bash(python3 *)
---
# Install lazy-observe

Bring up a Prometheus-format metrics shipper on the current host that scrapes every local lazycortex-core daemon's `/metrics` endpoint and forwards via `remote_write` to the operator's observer (self-hosted Prometheus / Mimir / etc.).

The plugin ships **observer-server-blind** templates only. This skill collects operator-private values (URL, token, basic-auth username, agent kind) at install time and persists them under `${XDG_CONFIG_HOME:-~/.config}/lazycortex/` — never in the plugin tree, never in tracked settings. These are GENUINE config that cannot be derived; the questions stay, but they are **read-first** — a value already on record is reused silently and never re-asked.

**Invocation modes** (from the skill arguments):

- *(no flag)* — full pre-flight: abort untouched when collection is already covered on this host.
- `--integrate-only` — do not install a shipper at all; regenerate the Prometheus file_sd scrape-targets file and print the one-time `file_sd_configs` snippet for the operator's existing Prometheus.
- `--force-standalone` — skip the pre-flight verdict and install the shipper anyway (the findings are still printed).

## File-sync policy (applies to every file this skill renders)

Every file this skill renders or writes (agent config, service unit from shipped templates) follows three cases — no per-file "install?" prompt, no drift wizard:

1. **Absent or unchanged** — target missing, or byte-identical to the freshly-rendered version → write silently. State `rendered` / `unchanged`.
2. **Locally changed but cleanly mergeable** — target diverged, but re-rendering only overwrites the generated region while every operator-owned value is preserved (no contradiction) → render silently. State `rendered`.
3. **Genuine conflict** — the same region was changed both locally and in the freshly-rendered version in ways that cannot be reconciled automatically → the ONLY case that asks. `AskUserQuestion` naming the file, quoting the conflicting region, options `take-rendered` / `keep-local`.

"Conflict" means you cannot determine what should survive — not merely "the bytes differ". Re-rendering = overwrite the generated region, preserve operator-owned values; no contradiction → no question.

## Read-first config (never re-ask)

Genuine config (`agent_kind`, `remote_write_url`, `auth_kind`, `basic_auth_username`) lives under `${XDG_CONFIG_HOME:-~/.config}/lazycortex/observe.toml`. Before any config question, read that file: if the value is already on record, reuse it silently and SKIP the question (outcome `kept-existing`). Ask only when nothing is on record. Persist every collected answer back so the next run is silent.

## Execution discipline (MANDATORY — read before any action)

This skill has 13 ordered steps. The executing agent MUST NOT skip, merge, reorder, or silently omit any step. To make dropped steps structurally impossible:

1. **Before calling any other tool**, call `TaskCreate` with exactly one task per step below — no merging, no abbreviation, no renaming. The canonical list (use these titles verbatim):
   - `Step 0 — Detect existing coverage (pre-flight)`
   - `Step 0.5 — Integrate-only: publish scrape targets`
   - `Step 1 — Detect host`
   - `Step 2 — Verify lazycortex-core metrics endpoints`
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

## Step 0 — Detect existing coverage (pre-flight)

**Before any question**, check whether metric collection is already working on this host:

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import json, install
print(json.dumps(install.detect_existing_coverage(), indent = 2))
"
```

The probe is read-only and looks at three local signal classes: an installed lazycortex-observe service unit, running scraper processes (prometheus / otelcol / alloy / grafana-agent), and live established connections to the daemons' metrics ports. A lone scraper process does NOT flip the verdict (it may serve something unrelated); an observe unit, an active scrape connection, or two independent process signals do.

- **Verdict `clear`** → state `clear`, mark Step 0.5 `skipped-not-integrate`, continue with Step 1.
- **Verdict `already-covered`, no flag** → print every detected signal verbatim, then **abort without asking a single question**: mark Steps 0.5–10 `skipped-already-covered` and jump to the Report. Tell the operator the two deliberate ways forward — re-run as `/lazy-observe.install --integrate-only` (feed the existing stack a target list, install nothing) or `/lazy-observe.install --force-standalone` (install a shipper anyway). The default action on a working stack is to not touch it.
- **Verdict `already-covered`, `--force-standalone`** → print the signals, state `force-standalone`, continue with Step 1.
- **`--integrate-only`** (any verdict) → state `integrate-mode`, persist `mode = "integrate"` into `observe.toml` via `install.write_answer_file`, continue with Step 0.5.

Outcome: `clear` / `already-covered-aborted` / `force-standalone` / `integrate-mode`.

## Step 0.5 — Integrate-only: publish scrape targets

Runs only in integrate mode; otherwise `skipped-not-integrate`.

No shipper, no service unit, no agent binary. Regenerate the host's scrape-targets file through the core CLI:

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import json, install
print(json.dumps(install.write_scrape_file_via_core(), indent = 2))
"
```

Then print the one-time snippet the operator adds to their existing Prometheus config (after this single edit, new daemons appear with no further manual changes — the targets file is regenerated by `lazy-core.install` whenever a daemon gains metrics):

```yaml
  - job_name: lazycortex-runtime
    file_sd_configs:
      - files:
          - <path printed by the command above>
        refresh_interval: 30s
```

Mark Steps 1–10 `skipped-integrate-mode` and jump to the Report.

Outcome: `published-<count>-targets` / `skipped-not-integrate`.

## Step 1 — Detect host

Call `python3 -c "import sys; print(sys.platform)"`. Map:

- `darwin` → use launchd (`com.lazycortex.observe.plist.j2`).
- `linux` → use systemd user unit (`lazycortex-observe.service.j2`).
- anything else → abort with outcome `unsupported-platform`.

Outcome: `darwin` / `linux` / `unsupported-platform`.

## Step 2 — Verify lazycortex-core metrics endpoints

List every metrics-enabled daemon on this host and probe each endpoint:

```bash
PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/bin python3 -c "
import install
targets = install.local_scrape_targets()
for t in targets:
    addr = ('127.0.0.1' if t['bind'] in ('0.0.0.0', '::') else t['bind']) + ':' + str(t['port'])
    print(t['repo_label'], addr, install.smoke_test_local_metrics(addr))
print('none-registered' if not targets else 'done')
"
```

- **No metrics-enabled daemons registered** → no scrape set exists; tell the operator to enable metrics via `/lazy-core.install` (Step 13.6 there provisions the port and label) and abort with outcome `core-metrics-disabled`.
- **Some endpoints down** → the daemons may simply be stopped; report each `repo_label → False` line and continue (the shipper config still covers them; scrapes succeed once the daemon starts).

Outcome: `reachable-<N>-of-<M>` / `core-metrics-disabled`.

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
- `mode` ∈ `{standalone, integrate}` (default `standalone`)
- `scrape_interval` (default `15s`)
- `wal_max_age` (default `12h`)
- `host_kind` ∈ `{darwin, linux}`

The scrape-target SET is never stored here — it is derived from the daemon registry (core CLI `daemon-list`) at render time, so daemons added later are picked up by a plain re-run.

The helper refuses to write any key named `token` or `LAZYCORTEX_OBSERVE_TOKEN` — defense-in-depth against accidental secret leakage.

Outcome: `persisted` (path: `${XDG_CONFIG_HOME:-~/.config}/lazycortex/observe.toml`).

## Step 7 — Render agent config

Call `install.render_to(<template>, vars, target)` where:

- `<template>` = `alloy.river.j2` if `agent_kind=alloy`, else `otelcol.yaml.j2`.
- `target` = `${XDG_DATA_HOME:-~/.local/share}/lazycortex/observe/agent.river` or `agent.yaml`.
- `vars` includes `scrape_targets_block = install.render_scrape_targets_block(install.local_scrape_targets(), agent_kind)` — the multi-target lines covering every metrics-enabled daemon on this host.

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

Then poll for up to 30s: `install.smoke_test_local_metrics(<target>)` for each target from Step 2 until at least one body contains `lazycortex_runtime`. If none ever does, surface the agent binary's own self-metrics endpoint (Alloy: `http://127.0.0.1:12345/-/ready`; otelcol: `http://127.0.0.1:8888/metrics`) for the operator to debug.

Outcome: `up` / `loaded-but-not-up`.

## Step 11 — Report

Render a markdown report. Severity: `PASS` / `WARN` / `FAIL`. One line per Step 0–10 with its outcome word. Include the answer-file path, rendered-config path, service-unit path (or the file_sd snippet in integrate mode), and the smoke-test summary.

Outcome: `reported`.

## Logging

Per the project's `lazy-log.logging` rule, log this run to `./.logs/claude/lazy-observe.install/<UTC timestamp>.md`. Frontmatter: `git_sha`, `git_branch`, `date`, `input`. Body: `## Actions` (one bullet per Step) and `## Result` (PASS/WARN/FAIL summary). Use `Bash(mkdir -p ...)` then `Write` — never chain.

## Failure modes

- **`/lazy-observe.install` stops immediately saying "collection is already covered on this host"** — the Step 0 pre-flight found a working stack (its signals are listed in the output) → this is the intended default on a host with an existing Prometheus/collector; re-run with `--integrate-only` to feed that stack a target list, or `--force-standalone` to install a shipper anyway.
- **Step 2 aborts: "no metrics-enabled daemons registered"** — no local daemon has `daemon.metrics.enabled: true` → enable metrics via `/lazy-core.install` (its metrics step allocates the port and label), then re-run.
- **Operator already has a different shipper running on the same launchctl label / unit name** — symptom: `bootstrap` / `enable` errors with "already loaded" → cause: previous install or operator-managed copy → fix: run `/lazy-observe.uninstall` first, then re-run install.
- **lazycortex-core daemon down** — symptom: Step 2 returns `core-metrics-disabled` even after enabling `metrics.enabled: true` → cause: daemon not started or not reloaded after settings flip → fix: restart the daemon supervisor (`launchctl kickstart -k gui/$UID com.lazycortex.runtime` or `systemctl --user restart lazycortex-runtime.service`).
- **remote_write 401/403 in agent self-metrics** — symptom: `prometheus_remote_storage_failed_samples_total` non-zero in agent's own scrape → cause: token wrong, expired, or missing scope → fix: rotate via `install.write_token_file(<new>)` and reload the service.
