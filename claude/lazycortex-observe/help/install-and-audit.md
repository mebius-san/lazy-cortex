---
chapter_type: block
summary: Install, verify health, and tear down the lazycortex-observe metrics shipper on any host.
last_regen: 2026-07-12
no_diagram: true
source_skills:
  - lazy-observe.install
  - lazy-observe.uninstall
  - lazy-observe.doctor
  - lazy-observe.audit
---
# Install and audit

Getting lazycortex-observe running on a new host — and keeping it running reliably — involves four skills that cover the full lifecycle: a wizard-driven install, a read-only health check you can run any time, a symmetric teardown, and a plugin audit that checks the plugin's own artifact conventions. Together they give you a reproducible, inspectable metrics shipper with no silent states.

## What's in this block

**`/lazy-observe.install`** is the entry point for every new host. Before asking anything, it pre-flight-checks whether this host already has a working collection stack (an installed observe service, a running scraper process, or a live scrape connection to your daemons) and, if so, aborts untouched rather than layering a second shipper on top — it prints the signals it found and points you at the two deliberate ways forward instead. From there it works through a wizard — detecting the platform, verifying every metrics-enabled lazycortex-core daemon's `/metrics` endpoint on this host, collecting your choice of agent (Grafana Alloy or the OpenTelemetry Collector), remote_write URL, and auth kind — then renders the agent config and the supervisor unit (launchd on macOS, systemd user unit on Linux) from the plugin's shipped templates, covering every local daemon in one scrape set. Operator-private values (the remote_write URL, bearer token or basic-auth credentials) land exclusively in `${XDG_CONFIG_HOME:-~/.config}/lazycortex/` and never in the plugin tree. Two flags change the default behavior: `--integrate-only` skips installing a shipper entirely and instead publishes a Prometheus file_sd scrape-targets file for a stack you already run; `--force-standalone` installs the shipper anyway even when the pre-flight found existing coverage. The skill is idempotent: re-running it rewrites the rendered configs and reloads the service, so it doubles as the update path when you need to change the agent kind, rotate the URL, or pick up a daemon added since the last run.

**`/lazy-observe.doctor`** is a read-only diagnostic you run any time the pipeline feels off. It checks the answer file, service unit state, agent process, every metrics-enabled daemon's local `/metrics` endpoint on this host, the agent's own remote_write success counters, observer URL reachability, and WAL directory size, reporting each as `PASS`, `WARN`, or `FAIL` with a one-line fix suggestion. When the host is running in integrate mode (no local shipper), doctor adjusts: instead of checking a service and agent process, it verifies the published scrape-targets file exists, parses, and its target count matches the live daemon count. It never restarts services or mutates anything; all it does is tell you what it sees. Run it right after install to confirm the smoke test passed, and again any time samples stop arriving in your observer.

**`/lazy-observe.uninstall`** is the symmetric undo. It unloads the service, removes the rendered agent config and service unit, and asks whether to keep or delete the WAL and log directories. Operator-private state — the answer file at `observe.toml` and the token file — is preserved by default, so a future reinstall on the same machine can skip the wizard prompts that already have answers. Both the WAL and the private state choices are explicit confirmations, not silent deletes. Re-running on an already-clean host is a no-op.

**`/lazy-observe.audit`** checks the plugin's own artifact conventions — rule-file frontmatter, execution-discipline preambles in skill and agent files, and logging-rule compliance. It is read-first and presents its findings before asking whether to apply any fix. Run it after upgrading the plugin or after making local edits to plugin files; it will surface any drift between what a skill declares and what the conventions require.

## How they work together

The typical lifecycle on a fresh machine is a straight line: run `/lazy-observe.install`, then `/lazy-observe.doctor` to confirm the pipeline is end-to-end healthy, then import the shipped Grafana dashboard and alert rules. After that, doctor becomes your ongoing pulse check — bookmark it for whenever you notice a gap in your dashboards or an alert fires.

If you already run a Prometheus or collector stack on the host, skip the standalone shipper: `/lazy-observe.install --integrate-only` publishes the scrape-targets file and prints the one-time `file_sd_configs` snippet to add to your existing config, and doctor adapts its checks to that mode automatically — no separate skill to learn.

When you need to change something — a new remote_write URL, a different agent kind, a rotated token, or a daemon that just got metrics enabled — re-run `/lazy-observe.install`. Because the skill is idempotent, it rewrites only what changed, picks up any new daemon automatically, and reloads the service. You do not need to uninstall first unless the service label or unit name itself is changing (and the install skill will tell you if it is, citing the existing loaded label).

Use `/lazy-observe.uninstall` when you are decommissioning the host or switching the machine out of the rotation entirely. The default of keeping the answer file and token means that if the machine comes back, a reinstall is a one-command operation with no wizard prompts to re-answer.

`/lazy-observe.audit` sits slightly apart from the operational loop — it inspects the plugin itself, not the running service. Run it after a minor-version upgrade of the plugin (a minor bump means re-running install to pick up new templates or settings, and audit confirms the plugin files landed correctly) or any time you have edited a plugin file locally and want to verify it still meets conventions.

If doctor reports a `FAIL not-installed`, the next step is always `/lazy-observe.install`. If it reports a service unit that is inactive (`FAIL inactive`), check the agent binary's own logs before restarting — doctor gives you the log path for both launchd and systemd. If it reports `WARN zero-rate` on the remote_write counter, check the observer URL reachability step in the same report: that step catching `FAIL unreachable` explains the zero rate and the fix is on the network side, not in the plugin.

## Where this fits

This block lives at the boundary between the lazycortex-observe plugin and your host infrastructure. The lazycortex-core daemon must be running with `metrics.enabled: true` before install makes sense — see the Quick Start section of the plugin README for the one-time core-side setting change. Because install and doctor both derive their scrape set from lazycortex-core's own daemon registry, a host running several repos' daemons at once is covered by a single shipper (or a single scrape-targets file in integrate mode) with no per-daemon setup step. Once the shipper is up, the dashboard and alert rule files shipped under `claude/lazycortex-observe/dashboards/` and `claude/lazycortex-observe/alerts/` are the observer-side complement; doctor's WAL and remote_write checks close the loop between the agent on your machine and the dashboards in your observer.
