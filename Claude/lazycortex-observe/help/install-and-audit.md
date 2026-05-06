---
chapter_type: block
summary: Install, verify health, and tear down the lazycortex-observe metrics shipper on any host.
last_regen: 2026-05-05
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

**`/lazy-observe.install`** is the entry point for every new host. It works through eleven ordered steps — detecting the platform, verifying the lazycortex-core `/metrics` endpoint, collecting your choice of agent (Grafana Alloy or the OpenTelemetry Collector), remote_write URL, and auth kind — then renders the agent config and the supervisor unit (launchd on macOS, systemd user unit on Linux) from the plugin's shipped templates. Operator-private values (the remote_write URL, bearer token or basic-auth credentials) land exclusively in `${XDG_CONFIG_HOME:-~/.config}/lazycortex/` and never in the plugin tree. The skill is idempotent: re-running it rewrites the rendered configs and reloads the service, so it doubles as the update path when you need to change the agent kind or rotate the URL.

**`/lazy-observe.doctor`** is a read-only diagnostic you run any time the pipeline feels off. It checks seven things in order — the answer file, service unit state, agent process, the local `/metrics` endpoint, the agent's own remote_write success counters, observer URL reachability, and WAL directory size — and reports each as `PASS`, `WARN`, or `FAIL` with a one-line fix suggestion. It never restarts services or mutates anything; all it does is tell you what it sees. Run it right after install to confirm the smoke test passed, and again any time samples stop arriving in your observer.

**`/lazy-observe.uninstall`** is the symmetric undo. It unloads the service, removes the rendered agent config and service unit, and asks whether to keep or delete the WAL and log directories. Operator-private state — the answer file at `observe.toml` and the token file — is preserved by default, so a future reinstall on the same machine can skip the wizard prompts that already have answers. Both the WAL and the private state choices are explicit confirmations, not silent deletes. Re-running on an already-clean host is a no-op.

**`/lazy-observe.audit`** checks the plugin's own artifact conventions — rule-file frontmatter, execution-discipline preambles in skill and agent files, and logging-rule compliance. It is read-first and presents its findings before asking whether to apply any fix. Run it after upgrading the plugin or after making local edits to plugin files; it will surface any drift between what a skill declares and what the conventions require.

## How they work together

The typical lifecycle on a fresh machine is a straight line: run `/lazy-observe.install`, then `/lazy-observe.doctor` to confirm the pipeline is end-to-end healthy, then import the shipped Grafana dashboard and alert rules. After that, doctor becomes your ongoing pulse check — bookmark it for whenever you notice a gap in your dashboards or an alert fires.

When you need to change something — a new remote_write URL, a different agent kind, a rotated token — re-run `/lazy-observe.install`. Because the skill is idempotent, it rewrites only what changed and reloads the service. You do not need to uninstall first unless the service label or unit name itself is changing (and the install skill will tell you if it is, citing the existing loaded label).

Use `/lazy-observe.uninstall` when you are decommissioning the host or switching the machine out of the rotation entirely. The default of keeping the answer file and token means that if the machine comes back, a reinstall is a one-command operation with no wizard prompts to re-answer.

`/lazy-observe.audit` sits slightly apart from the operational loop — it inspects the plugin itself, not the running service. Run it after a minor-version upgrade of the plugin (a minor bump means re-running install to pick up new templates or settings, and audit confirms the plugin files landed correctly) or any time you have edited a plugin file locally and want to verify it still meets conventions.

If doctor reports a `FAIL not-installed`, the next step is always `/lazy-observe.install`. If it reports a service unit that is inactive (`FAIL inactive`), check the agent binary's own logs before restarting — doctor gives you the log path for both launchd and systemd. If it reports `WARN zero-rate` on the remote_write counter, check the observer URL reachability step in the same report: that step catching `FAIL unreachable` explains the zero rate and the fix is on the network side, not in the plugin.

## Where this fits

This block lives at the boundary between the lazycortex-observe plugin and your host infrastructure. The lazycortex-core daemon must be running with `metrics.enabled: true` before install makes sense — see the Quick Start section of the plugin README for the one-time core-side setting change. Once the shipper is up, the dashboard and alert rule files shipped under `claude/lazycortex-observe/dashboards/` and `claude/lazycortex-observe/alerts/` are the observer-side complement; doctor's WAL and remote_write checks close the loop between the agent on your machine and the dashboards in your observer.
